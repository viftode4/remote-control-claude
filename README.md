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
- An OAuth token for the Anthropic API
- AnyDesk, TeamViewer, or any remote desktop software

## Quick Start

### 1. Install

```cmd
git clone <this-repo-url>
cd remote-control-claude
setup.bat
```

### 2. Start the Proxy

```cmd
start-proxy.bat
```

The proxy runs on port 9090 and forwards your OAuth token to Anthropic. No API key needed.

### 3. Start the Agent

```cmd
start-agent.bat
```

Open **http://localhost:8501** in your browser.

### 4. Configure the Agent UI

In the sidebar:
- **API Key**: Paste your OAuth token here
- **Proxy URL**: `http://localhost:9090/proxy/anthropic`

### 5. Use

1. Connect to your remote work PC via AnyDesk/TeamViewer
2. Set the remote desktop window to **full screen**
3. In the agent chat, describe what you want Claude to do:

> "My entire screen is an AnyDesk session to a remote computer. Open the Excel file on the desktop and copy the data from column A."

## OAuth Proxy

The proxy server forwards your OAuth token directly to Anthropic's API. No API key is stored anywhere on the server.

### Architecture

```
Agent UI  --[OAuth token]-->  Proxy  --[same OAuth token]-->  Anthropic API
```

Your OAuth token passes through as-is. The proxy adds:
- **Rate limiting** per user (60 req/min default)
- **Request logging** for auditing
- **Optional allowlist** to restrict which tokens can use the proxy

### Optional: Token Allowlist

To restrict which OAuth tokens can use the proxy, create `proxy/allowed_tokens.txt`:

```
# One token per line
sk-ant-token-1-here
sk-ant-token-2-here
```

If this file doesn't exist or is empty, any OAuth token is passed through.

### Proxy Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check, shows config status |
| `POST /proxy/anthropic/v1/messages` | Proxied Anthropic Messages API |

## Tips for Best Results

- Use **full-screen mode** in AnyDesk/TeamViewer for less visual noise
- Set remote desktop quality to **"Optimize speed"** for cleaner screenshots
- Set remote resolution to **1024x768** if possible (Claude's recommended resolution)
- Be explicit in prompts about what's on screen
- Set API billing limits -- screenshots consume significant tokens

## Configuration

All settings via environment variables in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `PROXY_PORT` | 9090 | Proxy server port |
| `PROXY_HOST` | 0.0.0.0 | Proxy server bind address |
| `RATE_LIMIT_PER_MINUTE` | 60 | Max requests per user per minute |
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
│   └── server.py            # Passthrough proxy with rate limiting
├── setup.bat                # One-time setup
├── start-agent.bat          # Start the agent UI
├── start-proxy.bat          # Start the proxy server
├── .env.example             # Configuration template
└── requirements.txt         # Python dependencies
```

## Security Considerations

- **Never give the agent access to sensitive credentials or accounts.** Claude follows instructions found in web content, which could override your instructions (prompt injection).
- Use the agent in a supervised manner -- watch what it does.
- The proxy should run on a trusted network.
- Your OAuth token is forwarded as-is to Anthropic. The proxy does not store it.

## Credits

Based on [Anthropic Computer Use](https://docs.anthropic.com/en/docs/build-with-claude/computer-use) and the [Windows adaptation](https://github.com/sunkencity999/windows_claude_computer_use) by Christopher Bradford.
