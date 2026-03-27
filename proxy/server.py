"""
OAuth Proxy Server for Anthropic API.

Pure passthrough proxy — the user's OAuth token IS the authentication.
No API key stored on the server. The proxy forwards the user's Bearer
token directly to Anthropic's API.

The proxy provides:
- Rate limiting per user
- Request logging / auditing
- Optional allowlist of permitted OAuth tokens
"""

import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("proxy")

ANTHROPIC_BASE_URL = os.getenv(
    "ANTHROPIC_BASE_URL_UPSTREAM", "https://api.anthropic.com"
)

# Optional: restrict to specific OAuth tokens (one per line)
# If empty or missing, any valid OAuth token is passed through.
ALLOWLIST_FILE = Path(__file__).parent / "allowed_tokens.txt"

# Rate limiting: max requests per user per minute
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))

app = FastAPI(
    title="Anthropic OAuth Proxy",
    description="Passthrough proxy that forwards OAuth Bearer tokens to the Anthropic API. No API key required.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory rate limiting
_rate_limits: dict[str, list[float]] = {}


def _hash_token(token: str) -> str:
    """Hash a token for rate limit tracking (never store raw tokens)."""
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


def _load_allowlist() -> set[str] | None:
    """Load optional token allowlist. Returns None if no allowlist (open mode)."""
    if not ALLOWLIST_FILE.exists():
        return None
    tokens = set()
    for line in ALLOWLIST_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            tokens.add(line)
    return tokens if tokens else None


def _extract_and_validate_token(request: Request) -> str:
    """Extract Bearer token from request, validate allowlist and rate limit."""
    auth_header = request.headers.get("authorization", "")

    # Accept both "Bearer xxx" and raw token in x-api-key header
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    elif request.headers.get("x-api-key"):
        token = request.headers["x-api-key"].strip()
    else:
        raise HTTPException(
            status_code=401,
            detail="Missing authentication. Provide your OAuth token as: Authorization: Bearer <token>",
        )

    if not token:
        raise HTTPException(status_code=401, detail="Empty token")

    # Check allowlist if configured
    allowlist = _load_allowlist()
    if allowlist is not None and token not in allowlist:
        logger.warning("Rejected token not in allowlist")
        raise HTTPException(status_code=403, detail="Token not in allowlist")

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
    allowlist = _load_allowlist()
    return {
        "status": "ok",
        "mode": "oauth_passthrough",
        "upstream": ANTHROPIC_BASE_URL,
        "allowlist_configured": allowlist is not None,
        "allowlisted_tokens": len(allowlist) if allowlist else "open (any token accepted)",
        "rate_limit_per_minute": RATE_LIMIT_PER_MINUTE,
    }


@app.api_route(
    "/proxy/anthropic/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def proxy_anthropic(request: Request, path: str) -> StreamingResponse:
    """
    Forward the request to Anthropic API with the user's own OAuth token.

    The user's Bearer token is passed through as-is — this proxy does NOT
    inject any server-side API key.
    """
    oauth_token = _extract_and_validate_token(request)

    # Build the target URL
    target_url = f"{ANTHROPIC_BASE_URL}/{path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    body = await request.body()

    # Build headers — forward the user's OAuth token to Anthropic
    forward_headers = {}
    for key, value in request.headers.items():
        lower_key = key.lower()
        if lower_key in ("host", "content-length", "transfer-encoding"):
            continue
        # Keep authorization and x-api-key as-is — it's the user's token
        forward_headers[key] = value

    # Ensure the token is sent both ways Anthropic might expect it
    forward_headers["x-api-key"] = oauth_token
    forward_headers["authorization"] = f"Bearer {oauth_token}"
    forward_headers.setdefault(
        "anthropic-version", "2023-06-01"
    )

    logger.info(
        "Proxying %s %s -> %s (user: %s)",
        request.method,
        request.url.path,
        target_url,
        _hash_token(oauth_token),
    )

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


def main() -> None:
    """Start the proxy server."""
    import uvicorn

    port = int(os.getenv("PROXY_PORT", "9090"))
    host = os.getenv("PROXY_HOST", "0.0.0.0")

    allowlist = _load_allowlist()
    mode = "allowlist" if allowlist else "open (any OAuth token)"

    print(f"\nAnthropic OAuth Proxy")
    print(f"{'=' * 40}")
    print(f"Mode:           {mode}")
    print(f"Upstream:       {ANTHROPIC_BASE_URL}")
    print(f"Proxy endpoint: http://localhost:{port}/proxy/anthropic")
    print(f"Health check:   http://localhost:{port}/health")
    print(f"Rate limit:     {RATE_LIMIT_PER_MINUTE} req/min per token")
    print()
    print(f"Users enter their OAuth token as the API key in the agent UI,")
    print(f"and set the Proxy URL to: http://localhost:{port}/proxy/anthropic")
    print()

    if allowlist:
        print(f"Allowlisted tokens: {len(allowlist)} (from {ALLOWLIST_FILE})")
    else:
        print(f"No allowlist — any OAuth token will be passed through.")
        print(f"To restrict access, add tokens to {ALLOWLIST_FILE}")
    print()

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
