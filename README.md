# Remote Control Agent

AI-powered desktop automation agent that uses Claude to control a remote computer via AnyDesk, TeamViewer, or any remote desktop software.

## How It Works

```
Your PC (runs the agent)  -->  AnyDesk/TeamViewer  -->  Remote Work PC
         |
    Claude AI sees your screen,
    sends mouse clicks & keystrokes
    through the remote desktop window
```

The agent takes screenshots of your screen, sends them to Claude, and Claude responds with mouse/keyboard actions. If a remote desktop window (AnyDesk, TeamViewer, etc.) is open full-screen, Claude interacts with the remote machine through it.

**Nothing needs to be installed on the remote computer.** The agent runs entirely on your local machine.

## Requirements

- Windows 10 or later
- Python 3.10 - 3.13
- Anthropic API key ([get one here](https://console.anthropic.com/))
- AnyDesk, TeamViewer, or any remote desktop software

## Quick Start

### 1. Install

```cmd
git clone <this-repo-url>
cd remote-control-claude
setup.bat
```

This creates a virtual environment and installs all dependencies.

### 2. Configure

Edit the `.env` file and set your API key:

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

### 3. Run

```cmd
start-agent.bat
```

Open **http://localhost:8501** in your browser. You'll see a chat interface.

### 4. Use

1. Connect to your remote work PC via AnyDesk/TeamViewer
2. Set the remote desktop window to **full screen**
3. In the agent chat, describe what you want Claude to do:

> "My entire screen is an AnyDesk session to a remote computer. Open the Excel file on the desktop and copy the data from column A."

Claude will take screenshots, analyze them, and send mouse/keyboard actions to complete the task.

## OAuth Proxy (Team Use)

For team deployments, the proxy server lets multiple users access Claude without sharing the raw API key. Users authenticate with individual tokens instead.

### Architecture

```
User's Agent  --[Bearer token]-->  Proxy Server  --[API key]-->  Anthropic API
```

The API key stays on the proxy server. Users only receive a Bearer token.

### Setup

**On the machine hosting the proxy:**

1. Set `ANTHROPIC_API_KEY` in `.env`
2. Start the proxy:
   ```cmd
   start-proxy.bat
   ```
3. Generate tokens for each user:
   ```cmd
   generate-token.bat
   ```
   Share the printed token with the user.

**On each user's machine:**

1. Install the agent (see Quick Start)
2. In the agent sidebar, set:
   - **API Key**: the token you received
   - **Proxy URL**: `http://<proxy-host>:9090/proxy/anthropic`

### Proxy Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check, shows config status |
| `POST /proxy/anthropic/v1/messages` | Proxied Anthropic Messages API |
| `POST /token/refresh` | Refresh a token (send old token as Bearer) |

### Token Lifecycle

Tokens expire after **24 hours** by default (configurable via `TOKEN_EXPIRY_SECONDS`).

**Refresh:** Before a token expires (or within 7 days after), call:
```
POST /token/refresh
Authorization: Bearer <old-token>
```
Response:
```json
{
  "access_token": "new-token-here",
  "token_type": "bearer",
  "expires_in": 86400
}
```

**Management commands:**
```cmd
:: List all tokens and their status
python -m proxy.server list-tokens

:: Revoke a token by prefix
python -m proxy.server revoke-token abc123

:: Generate a labeled token
python -m proxy.server generate-token john
```

Tokens are stored in `proxy/authorized_tokens.json`. The proxy reloads tokens on every request, so changes take effect immediately.

## Tips for Best Results

- Use **full-screen mode** in AnyDesk/TeamViewer for less visual noise
- Set remote desktop quality to **"Optimize speed"** for cleaner screenshots
- Set remote resolution to **1024x768** if possible (Claude's recommended resolution)
- Be explicit in prompts about what's on screen
- Set API billing limits -- screenshots consume significant tokens

## Configuration

All settings can be configured via environment variables in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | (required) | Your Anthropic API key |
| `ANTHROPIC_BASE_URL` | (none) | Proxy URL, if using the proxy |
| `PROXY_PORT` | 9090 | Proxy server port |
| `PROXY_HOST` | 0.0.0.0 | Proxy server bind address |
| `RATE_LIMIT_PER_MINUTE` | 60 | Max requests per token per minute |
| `TOKEN_EXPIRY_SECONDS` | 86400 | Token lifetime (0 = never expire) |
| `WIDTH` | auto | Override screen width for screenshots |
| `HEIGHT` | auto | Override screen height for screenshots |

## Project Structure

```
remote-control-claude/
├── computer_use_demo/       # Agent core (screenshot, mouse, keyboard)
│   ├── loop.py              # Main agent loop (calls Claude API)
│   ├── streamlit.py         # Web UI
│   └── tools/               # Computer control tools
├── proxy/                   # OAuth proxy server
│   └── server.py            # FastAPI proxy with token auth
├── setup.bat                # One-time setup
├── start-agent.bat          # Start the agent UI
├── start-proxy.bat          # Start the proxy server
├── generate-token.bat       # Generate user tokens
├── .env.example             # Configuration template
└── requirements.txt         # Python dependencies
```

## Security Considerations

- **Never give the agent access to sensitive credentials or accounts.** Claude follows instructions found in web content, which could override your instructions (prompt injection).
- Use the agent in a supervised manner -- watch what it does.
- The proxy server should run on a trusted network. Use a firewall or VPN if exposing it.
- Rotate tokens periodically. Revoke tokens for users who no longer need access.
- Set API spending limits on your Anthropic account.

## Cost

Computer use is token-intensive. Each interaction loop sends a full screenshot (PNG image) to the Claude API. A single task can consume dozens of API calls. Monitor your usage at [console.anthropic.com](https://console.anthropic.com/).

## Credits

Based on [Anthropic Computer Use](https://docs.anthropic.com/en/docs/build-with-claude/computer-use) and the [Windows adaptation](https://github.com/sunkencity999/windows_claude_computer_use) by Christopher Bradford.
