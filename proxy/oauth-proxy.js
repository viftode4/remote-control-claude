const http = require("http");
const https = require("https");
const fs = require("fs");
const path = require("path");

// ── Config ──────────────────────────────────────────────────────────

const CONFIG_PATH = path.join(__dirname, "config.json");
const CREDENTIALS_PATH = path.join(
  process.env.HOME || process.env.USERPROFILE,
  ".claude",
  ".credentials.json"
);
const ANTHROPIC_API = "api.anthropic.com";
const TOKEN_URL = "console.anthropic.com";
const CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e";
const API_VERSION = "2023-06-01";

function loadConfig() {
  try {
    const raw = fs.readFileSync(CONFIG_PATH, "utf8");
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

let config = loadConfig();

// Watch config file for live reloads
fs.watchFile(CONFIG_PATH, { interval: 2000 }, () => {
  try {
    config = loadConfig();
    log("Config reloaded");
  } catch (e) {
    log("Config reload failed:", e.message);
  }
});

function cfg(key, fallback) {
  return config[key] !== undefined ? config[key] : fallback;
}

// ── Token Management ────────────────────────────────────────────────

let cachedToken = null;
let cachedExpiry = 0;
let refreshInFlight = null;

function loadCredentials() {
  const raw = fs.readFileSync(CREDENTIALS_PATH, "utf8");
  return JSON.parse(raw);
}

function saveCredentials(creds) {
  fs.writeFileSync(CREDENTIALS_PATH, JSON.stringify(creds, null, 2), "utf8");
}

function httpsPost(hostname, urlPath, body) {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify(body);
    const req = https.request(
      {
        hostname,
        port: 443,
        path: urlPath,
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(payload),
        },
      },
      (res) => {
        let data = "";
        res.on("data", (c) => (data += c));
        res.on("end", () => {
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve(JSON.parse(data));
          } else {
            reject(new Error(`HTTP ${res.statusCode}: ${data}`));
          }
        });
      }
    );
    req.on("error", reject);
    req.setTimeout(15000, () => {
      req.destroy();
      reject(new Error("Request timeout"));
    });
    req.write(payload);
    req.end();
  });
}

async function refreshToken() {
  if (refreshInFlight) return refreshInFlight;

  refreshInFlight = (async () => {
    try {
      const creds = loadCredentials();
      const oauth = creds.claudeAiOauth;

      if (!oauth || !oauth.refreshToken) {
        throw new Error("No refresh token in credentials file");
      }

      const resp = await httpsPost(TOKEN_URL, "/v1/oauth/token", {
        grant_type: "refresh_token",
        refresh_token: oauth.refreshToken,
        client_id: CLIENT_ID,
      });

      oauth.accessToken = resp.access_token;
      if (resp.refresh_token) oauth.refreshToken = resp.refresh_token;
      oauth.expiresAt = Date.now() + resp.expires_in * 1000;

      saveCredentials(creds);

      cachedToken = resp.access_token;
      cachedExpiry = oauth.expiresAt;

      log(
        "Token refreshed, expires",
        new Date(cachedExpiry).toLocaleTimeString()
      );
      return cachedToken;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

async function getToken() {
  if (cachedToken && cachedExpiry > Date.now() + 60000) {
    return cachedToken;
  }

  const creds = loadCredentials();
  const oauth = creds.claudeAiOauth;

  if (oauth && oauth.accessToken && oauth.expiresAt > Date.now() + 60000) {
    cachedToken = oauth.accessToken;
    cachedExpiry = oauth.expiresAt;
    return cachedToken;
  }

  return refreshToken();
}

// ── Proxy ───────────────────────────────────────────────────────────

function resolveModel(name) {
  if (!name) return cfg("default_model", "claude-sonnet-4-6");

  const aliases = config.models || {};
  return aliases[name] || name;
}

function proxyToAnthropic(token, body) {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify(body);
    const req = https.request(
      {
        hostname: ANTHROPIC_API,
        port: 443,
        path: "/v1/messages",
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          "anthropic-version": API_VERSION,
          "anthropic-beta":
            "claude-code-20250219,oauth-2025-04-20,interleaved-thinking-2025-05-14,computer-use-2024-10-22,prompt-caching-2024-07-31",
          "Content-Length": Buffer.byteLength(payload),
        },
      },
      (res) => resolve(res)
    );
    req.on("error", reject);
    req.setTimeout(cfg("timeout_ms", 120000), () => {
      req.destroy();
      reject(new Error("Upstream timeout"));
    });
    req.write(payload);
    req.end();
  });
}

function stripTtlFromCacheControl(obj) {
  if (!obj || typeof obj !== "object") return;

  const processArray = (arr) => {
    if (!Array.isArray(arr)) return;
    for (const item of arr) {
      if (item && item.cache_control && item.cache_control.ttl) {
        delete item.cache_control.ttl;
      }
    }
  };

  if (Array.isArray(obj.system)) processArray(obj.system);
  if (Array.isArray(obj.messages)) {
    for (const msg of obj.messages) {
      if (Array.isArray(msg.content)) processArray(msg.content);
    }
  }
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (c) => (data += c));
    req.on("end", () => {
      try {
        resolve(data ? JSON.parse(data) : {});
      } catch (e) {
        reject(new Error("Invalid JSON"));
      }
    });
    req.on("error", reject);
  });
}

function log(...args) {
  if (!cfg("log_requests", true) && args[0]?.startsWith?.("→")) return;
  const ts = new Date().toLocaleTimeString();
  const line = `[${ts}] ${args.join(" ")}`;
  console.log(line);

  const logFile = cfg("log_file", null);
  if (logFile) {
    fs.appendFileSync(logFile, line + "\n");
  }
}

// ── Request Stats ───────────────────────────────────────────────────

let stats = { requests: 0, errors: 0, started: Date.now() };

// ── Server ──────────────────────────────────────────────────────────

const server = http.createServer(async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader(
    "Access-Control-Allow-Headers",
    "Content-Type, Authorization, X-Api-Key, anthropic-version, anthropic-beta"
  );

  if (req.method === "OPTIONS") {
    res.writeHead(200);
    res.end();
    return;
  }

  // ── Health ──
  if (req.url === "/health") {
    const tokenOk = cachedToken && cachedExpiry > Date.now();
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        status: "ok",
        authenticated: tokenOk,
        default_model: cfg("default_model", "claude-sonnet-4-6"),
        expires_at: cachedExpiry ? new Date(cachedExpiry).toISOString() : null,
        uptime: process.uptime(),
        requests: stats.requests,
        errors: stats.errors,
      })
    );
    return;
  }

  // ── Config (live view + update) ──
  if (req.url === "/config" && req.method === "GET") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(config, null, 2));
    return;
  }

  if (req.url === "/config" && req.method === "POST") {
    try {
      const newConfig = await readBody(req);
      const merged = { ...config, ...newConfig };
      fs.writeFileSync(CONFIG_PATH, JSON.stringify(merged, null, 2), "utf8");
      config = merged;
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true, config: merged }));
      log("Config updated via API");
    } catch (e) {
      res.writeHead(400, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: e.message }));
    }
    return;
  }

  // ── Model list ──
  if (req.url === "/v1/models" && req.method === "GET") {
    const aliases = config.models || {};
    const models = Object.entries(aliases).map(([alias, id]) => ({
      id,
      alias,
      object: "model",
    }));
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ object: "list", data: models }));
    return;
  }

  // ── OpenAI-compatible endpoint (translates to Anthropic) ──
  if (req.method === "POST" && req.url.startsWith("/v1/chat/completions")) {
    stats.requests++;
    try {
      const oaiBody = await readBody(req);

      // Convert OpenAI format → Anthropic format
      const messages = (oaiBody.messages || []).filter((m) => m.role !== "system");
      const systemMsgs = (oaiBody.messages || []).filter((m) => m.role === "system");
      const systemText = systemMsgs.map((m) => m.content).join("\n");

      const anthropicBody = {
        model: resolveModel(oaiBody.model),
        max_tokens: oaiBody.max_tokens || cfg("max_tokens", 8192),
        messages: messages.map((m) => ({
          role: m.role === "assistant" ? "assistant" : "user",
          content: m.content,
        })),
      };

      if (oaiBody.temperature !== undefined) anthropicBody.temperature = oaiBody.temperature;
      if (oaiBody.stream) anthropicBody.stream = true;

      // System prompt
      const codePrompt = {
        type: "text",
        text: "You are Claude Code, Anthropic's official CLI for Claude.",
      };
      anthropicBody.system = [codePrompt];
      if (systemText) {
        anthropicBody.system.push({ type: "text", text: systemText });
      }

      log(`→ [OAI] ${anthropicBody.model} max_tokens=${anthropicBody.max_tokens} stream=${!!anthropicBody.stream}`);

      let token = await getToken();
      let upstream = await proxyToAnthropic(token, anthropicBody);

      if (upstream.statusCode === 401) {
        cachedToken = null;
        token = await refreshToken();
        upstream = await proxyToAnthropic(token, anthropicBody);
      }

      // Non-streaming: read full response and convert to OpenAI format
      if (!anthropicBody.stream) {
        let data = "";
        upstream.on("data", (c) => (data += c));
        upstream.on("end", () => {
          try {
            const antResp = JSON.parse(data);
            const content = (antResp.content || []).map((b) => b.text).join("");
            const oaiResp = {
              id: antResp.id || "chatcmpl-proxy",
              object: "chat.completion",
              model: antResp.model,
              choices: [
                {
                  index: 0,
                  message: { role: "assistant", content },
                  finish_reason: antResp.stop_reason === "end_turn" ? "stop" : antResp.stop_reason,
                },
              ],
              usage: {
                prompt_tokens: antResp.usage?.input_tokens || 0,
                completion_tokens: antResp.usage?.output_tokens || 0,
                total_tokens: (antResp.usage?.input_tokens || 0) + (antResp.usage?.output_tokens || 0),
              },
            };
            res.writeHead(upstream.statusCode, { "Content-Type": "application/json" });
            res.end(JSON.stringify(oaiResp));
          } catch (e) {
            res.writeHead(upstream.statusCode, { "Content-Type": "application/json" });
            res.end(data);
          }
        });
      } else {
        // Streaming: pass through SSE (not converted, litellm handles Anthropic SSE)
        const fwdHeaders = {};
        for (const [k, v] of Object.entries(upstream.headers)) {
          if (k !== "content-encoding") fwdHeaders[k] = v;
        }
        res.writeHead(upstream.statusCode, fwdHeaders);
        upstream.pipe(res);
      }

      upstream.on("error", () => { if (!res.destroyed) res.end(); });
      res.on("close", () => { if (!upstream.destroyed) upstream.destroy(); });
    } catch (err) {
      stats.errors++;
      log("ERROR:", err.message);
      if (!res.headersSent) res.writeHead(502, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: err.message }));
    }
    return;
  }

  // ── Anthropic-native endpoint ──
  if (req.method === "POST" && req.url.startsWith("/v1/messages")) {
    stats.requests++;
    try {
      const body = await readBody(req);
      stripTtlFromCacheControl(body);

      // Resolve model aliases and apply defaults
      body.model = resolveModel(body.model);
      if (!body.max_tokens) body.max_tokens = cfg("max_tokens", 8192);
      if (body.temperature === undefined && cfg("temperature", null) !== null) {
        body.temperature = cfg("temperature", 0.0);
      }

      // Inject required Claude Code system prompt (Anthropic requires this for OAuth)
      const codePrompt = {
        type: "text",
        text: "You are Claude Code, Anthropic's official CLI for Claude.",
      };
      if (!body.system) {
        body.system = [codePrompt];
      } else if (Array.isArray(body.system)) {
        body.system.unshift(codePrompt);
      } else {
        body.system = [codePrompt, { type: "text", text: body.system }];
      }

      log(
        `→ ${body.model} max_tokens=${body.max_tokens} stream=${!!body.stream}`
      );

      let token = await getToken();
      let upstream = await proxyToAnthropic(token, body);

      // Auto-retry on 401
      if (upstream.statusCode === 401) {
        log("Got 401, refreshing token...");
        cachedToken = null;
        token = await refreshToken();
        upstream = await proxyToAnthropic(token, body);
      }

      // Forward status and headers
      const fwdHeaders = {};
      for (const [k, v] of Object.entries(upstream.headers)) {
        if (k !== "content-encoding") fwdHeaders[k] = v;
      }
      res.writeHead(upstream.statusCode, fwdHeaders);

      upstream.pipe(res);
      upstream.on("error", () => {
        if (!res.destroyed) res.end();
      });
      res.on("close", () => {
        if (!upstream.destroyed) upstream.destroy();
      });
    } catch (err) {
      stats.errors++;
      log("ERROR:", err.message);
      if (!res.headersSent) {
        res.writeHead(502, { "Content-Type": "application/json" });
      }
      res.end(JSON.stringify({ error: err.message }));
    }
    return;
  }

  res.writeHead(404, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ error: "Not found" }));
});

const port = cfg("port", 8082);
const host = cfg("host", "127.0.0.1");

server.listen(port, host, () => {
  log(`Claude proxy listening on http://${host}:${port}`);
  log(`Config: ${CONFIG_PATH}`);
  log(`Default model: ${cfg("default_model", "claude-sonnet-4-6")}`);
  log(`Models: ${Object.keys(config.models || {}).join(", ")}`);

  getToken()
    .then(() => log("Token loaded, ready"))
    .catch((e) =>
      log("Token load failed:", e.message, "— will retry on first request")
    );
});
