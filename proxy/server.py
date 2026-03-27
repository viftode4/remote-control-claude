"""
OAuth Proxy Server for Anthropic API.

This proxy sits between the computer use agent and the Anthropic API.
It accepts requests authenticated with Bearer tokens (OAuth) and forwards
them to the Anthropic API using the real API key stored server-side.

This way, team members never need the raw Anthropic API key -- they only
need a proxy token issued by the administrator.

Tokens have configurable expiration and can be refreshed via the /token/refresh
endpoint using the original token before it expires.
"""

import hashlib
import json
import logging
import os
import secrets
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("proxy")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = "https://api.anthropic.com"

# Token storage
TOKENS_FILE = Path(__file__).parent / "authorized_tokens.json"

# Token expiration in seconds (default: 24 hours, 0 = never expire)
TOKEN_EXPIRY_SECONDS = int(os.getenv("TOKEN_EXPIRY_SECONDS", str(24 * 60 * 60)))

# Rate limiting: max requests per token per minute
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))

app = FastAPI(
    title="Anthropic OAuth Proxy",
    description="Proxy server that authenticates via Bearer tokens and forwards requests to the Anthropic API.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory rate limiting store
_rate_limits: dict[str, list[float]] = {}


@dataclass(frozen=True)
class TokenRecord:
    token: str
    label: str
    created_at: float
    expires_at: float  # 0 = never expires
    revoked: bool


def _load_tokens() -> dict[str, dict]:
    """Load token records from the JSON file."""
    if not TOKENS_FILE.exists():
        return {}
    try:
        data = json.loads(TOKENS_FILE.read_text())
        return data.get("tokens", {})
    except (json.JSONDecodeError, KeyError):
        return {}


def _save_tokens(tokens: dict[str, dict]) -> None:
    """Save token records to the JSON file."""
    TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKENS_FILE.write_text(json.dumps({"tokens": tokens}, indent=2))


def _hash_token(token: str) -> str:
    """Hash a token for rate limit tracking."""
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def _check_rate_limit(token_hash: str) -> bool:
    """Return True if the request is within rate limits."""
    now = time.time()
    window_start = now - 60

    if token_hash not in _rate_limits:
        _rate_limits[token_hash] = []

    _rate_limits[token_hash] = [
        ts for ts in _rate_limits[token_hash] if ts > window_start
    ]

    if len(_rate_limits[token_hash]) >= RATE_LIMIT_PER_MINUTE:
        return False

    _rate_limits[token_hash].append(now)
    return True


def _validate_bearer_token(request: Request) -> str:
    """Extract and validate the Bearer token from the request."""
    auth_header = request.headers.get("authorization", "")

    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header. Use: Bearer <token>",
        )

    token = auth_header[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty bearer token")

    tokens = _load_tokens()

    if not tokens:
        raise HTTPException(
            status_code=503,
            detail="No authorized tokens configured. Run generate-token.bat first.",
        )

    record = tokens.get(token)
    if record is None:
        logger.warning("Rejected unauthorized token attempt")
        raise HTTPException(status_code=403, detail="Invalid or revoked token")

    if record.get("revoked", False):
        logger.warning("Rejected revoked token: %s", record.get("label", "unknown"))
        raise HTTPException(status_code=403, detail="Token has been revoked")

    # Check expiration
    expires_at = record.get("expires_at", 0)
    if expires_at > 0 and time.time() > expires_at:
        remaining = -1
        raise HTTPException(
            status_code=401,
            detail="Token has expired. Use POST /token/refresh to get a new one.",
            headers={"X-Token-Expired": "true"},
        )

    # Rate limiting
    token_hash = _hash_token(token)
    if not _check_rate_limit(token_hash):
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded ({RATE_LIMIT_PER_MINUTE} requests/minute)",
        )

    return token


@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    has_api_key = bool(ANTHROPIC_API_KEY)
    tokens = _load_tokens()
    active_tokens = sum(
        1 for t in tokens.values()
        if not t.get("revoked", False)
        and (t.get("expires_at", 0) == 0 or time.time() < t.get("expires_at", 0))
    )
    return {
        "status": "ok",
        "anthropic_api_key_configured": has_api_key,
        "total_tokens": len(tokens),
        "active_tokens": active_tokens,
        "token_expiry_seconds": TOKEN_EXPIRY_SECONDS,
    }


@app.post("/token/refresh")
async def refresh_token(request: Request) -> JSONResponse:
    """
    Refresh an existing token before it expires.

    Send the current token as a Bearer header. If valid (even if expired within
    a grace period of 7 days), a new token is issued and the old one is revoked.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")

    old_token = auth_header[7:].strip()
    tokens = _load_tokens()
    record = tokens.get(old_token)

    if record is None:
        raise HTTPException(status_code=403, detail="Unknown token")

    if record.get("revoked", False):
        raise HTTPException(status_code=403, detail="Token has been permanently revoked")

    # Allow refresh within a 7-day grace period after expiry
    expires_at = record.get("expires_at", 0)
    grace_period = 7 * 24 * 60 * 60  # 7 days
    if expires_at > 0 and time.time() > (expires_at + grace_period):
        raise HTTPException(
            status_code=403,
            detail="Token expired beyond the 7-day refresh grace period. Request a new token from your administrator.",
        )

    # Generate new token
    now = time.time()
    new_token = secrets.token_urlsafe(32)
    new_expires = now + TOKEN_EXPIRY_SECONDS if TOKEN_EXPIRY_SECONDS > 0 else 0

    # Revoke old token
    record["revoked"] = True
    record["revoked_at"] = now
    record["replaced_by"] = _hash_token(new_token)
    tokens[old_token] = record

    # Create new token record
    tokens[new_token] = {
        "label": record.get("label", "unknown"),
        "created_at": now,
        "expires_at": new_expires,
        "revoked": False,
        "refreshed_from": _hash_token(old_token),
    }

    _save_tokens(tokens)

    logger.info("Token refreshed for user: %s", record.get("label", "unknown"))

    return JSONResponse({
        "access_token": new_token,
        "token_type": "bearer",
        "expires_in": TOKEN_EXPIRY_SECONDS if TOKEN_EXPIRY_SECONDS > 0 else None,
        "expires_at": new_expires if new_expires > 0 else None,
    })


@app.api_route(
    "/proxy/anthropic/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def proxy_anthropic(request: Request, path: str) -> StreamingResponse:
    """
    Forward authenticated requests to the Anthropic API.

    The agent points its base URL to http://localhost:9090/proxy/anthropic
    and this proxy swaps the Bearer token for the real API key.
    """
    _validate_bearer_token(request)

    if not ANTHROPIC_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY not configured on the proxy server",
        )

    target_url = f"{ANTHROPIC_BASE_URL}/{path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    body = await request.body()

    # Build headers -- replace auth with real API key
    forward_headers = {}
    for key, value in request.headers.items():
        lower_key = key.lower()
        if lower_key in ("host", "authorization", "content-length", "transfer-encoding"):
            continue
        forward_headers[key] = value

    forward_headers["x-api-key"] = ANTHROPIC_API_KEY
    forward_headers["anthropic-version"] = request.headers.get(
        "anthropic-version", "2023-06-01"
    )

    logger.info("Proxying %s %s -> %s", request.method, request.url.path, target_url)

    # Check if the request wants streaming
    is_streaming = False
    if body:
        try:
            body_json = json.loads(body)
            is_streaming = body_json.get("stream", False)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

    async with httpx.AsyncClient(timeout=300.0) as client:
        if is_streaming:
            upstream_response = await client.send(
                client.build_request(
                    method=request.method,
                    url=target_url,
                    headers=forward_headers,
                    content=body,
                ),
                stream=True,
            )

            async def stream_body():
                async for chunk in upstream_response.aiter_bytes():
                    yield chunk
                await upstream_response.aclose()

            response_headers = dict(upstream_response.headers)
            response_headers.pop("content-length", None)
            response_headers.pop("transfer-encoding", None)

            return StreamingResponse(
                stream_body(),
                status_code=upstream_response.status_code,
                headers=response_headers,
            )
        else:
            response = await client.request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
                content=body,
            )

            response_headers = dict(response.headers)
            response_headers.pop("content-length", None)
            response_headers.pop("transfer-encoding", None)
            response_headers.pop("content-encoding", None)

            return StreamingResponse(
                iter([response.content]),
                status_code=response.status_code,
                headers=response_headers,
            )


def generate_token(label: str = "user") -> str:
    """Generate a new token with expiration and save it."""
    now = time.time()
    token = secrets.token_urlsafe(32)
    expires_at = now + TOKEN_EXPIRY_SECONDS if TOKEN_EXPIRY_SECONDS > 0 else 0

    tokens = _load_tokens()
    tokens[token] = {
        "label": label,
        "created_at": now,
        "expires_at": expires_at,
        "revoked": False,
    }
    _save_tokens(tokens)
    return token, expires_at


def main() -> None:
    """CLI entry point for managing the proxy."""
    import uvicorn

    if len(sys.argv) > 1 and sys.argv[1] == "generate-token":
        label = sys.argv[2] if len(sys.argv) > 2 else "user"
        token, expires_at = generate_token(label)

        print(f"\nGenerated new token for '{label}':\n")
        print(f"  {token}\n")
        if expires_at > 0:
            from datetime import datetime
            exp_str = datetime.fromtimestamp(expires_at).strftime("%Y-%m-%d %H:%M:%S")
            hours = TOKEN_EXPIRY_SECONDS / 3600
            print(f"  Expires: {exp_str} ({hours:.0f} hours)")
            print(f"  Refresh: POST /token/refresh with this token before expiry")
            print(f"  Grace period: 7 days after expiry for refresh")
        else:
            print("  Expires: never")
        print(f"\n  Token saved to {TOKENS_FILE}")
        print("  Share this token with the user. They enter it as the API key in the agent UI.")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "list-tokens":
        tokens = _load_tokens()
        if not tokens:
            print("No tokens configured.")
            return
        print(f"\n{'Label':<15} {'Status':<12} {'Created':<20} {'Expires':<20}")
        print("-" * 70)
        from datetime import datetime
        for token_val, record in tokens.items():
            label = record.get("label", "unknown")
            revoked = record.get("revoked", False)
            expires = record.get("expires_at", 0)
            created = datetime.fromtimestamp(record.get("created_at", 0)).strftime("%Y-%m-%d %H:%M")

            if revoked:
                status = "revoked"
            elif expires > 0 and time.time() > expires:
                status = "expired"
            else:
                status = "active"

            exp_str = datetime.fromtimestamp(expires).strftime("%Y-%m-%d %H:%M") if expires > 0 else "never"
            preview = token_val[:8] + "..."
            print(f"{label:<15} {status:<12} {created:<20} {exp_str:<20} {preview}")
        print()
        return

    if len(sys.argv) > 1 and sys.argv[1] == "revoke-token":
        if len(sys.argv) < 3:
            print("Usage: python -m proxy.server revoke-token <token-prefix>")
            return
        prefix = sys.argv[2]
        tokens = _load_tokens()
        found = False
        for token_val, record in tokens.items():
            if token_val.startswith(prefix):
                record["revoked"] = True
                record["revoked_at"] = time.time()
                found = True
                print(f"Revoked token: {token_val[:8]}... (label: {record.get('label', 'unknown')})")
        if found:
            _save_tokens(tokens)
        else:
            print(f"No token found starting with '{prefix}'")
        return

    if not ANTHROPIC_API_KEY:
        print("WARNING: ANTHROPIC_API_KEY environment variable is not set!")
        print("Set it in .env or as an environment variable before starting the proxy.\n")

    port = int(os.getenv("PROXY_PORT", "9090"))
    host = os.getenv("PROXY_HOST", "0.0.0.0")

    print(f"\nStarting Anthropic OAuth Proxy on {host}:{port}")
    print(f"Proxy endpoint: http://localhost:{port}/proxy/anthropic")
    print(f"Health check:   http://localhost:{port}/health")
    print(f"Token refresh:  POST http://localhost:{port}/token/refresh")
    print(f"Token expiry:   {TOKEN_EXPIRY_SECONDS}s ({TOKEN_EXPIRY_SECONDS/3600:.0f}h)")
    print(f"Tokens file:    {TOKENS_FILE}\n")

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
