# Remote Control Agent

Use Claude to operate a remote work computer through AnyDesk or TeamViewer. Claude sees the screen, clicks, types, and scrolls — just like a person sitting at the remote desk.

**Nothing gets installed on the remote computer.** Everything runs on your local machine.

Uses your existing Claude subscription (OAuth). No API key needed.

---

## What You Need

- **Windows 10+**
- **Python 3.10–3.13** ([python.org](https://python.org))
- **Node.js** ([nodejs.org](https://nodejs.org))
- **Claude Code** installed and logged in ([install guide](https://docs.anthropic.com/en/docs/claude-code))
- **AnyDesk** or **TeamViewer** (or any remote desktop app)

---

## Setup

Open a terminal (Command Prompt or PowerShell) and run these commands.

### 1. Clone this repo

```cmd
git clone https://github.com/viftode4/remote-control-claude.git
cd remote-control-claude
```

### 2. Install Python dependencies

```cmd
pip install -r requirements.txt
```

### 3. Set up the OAuth proxy

The proxy handles authentication using your Claude Code login. Run this once:

```cmd
mkdir "%USERPROFILE%\.claude\proxy"
copy proxy\oauth-proxy.js "%USERPROFILE%\.claude\proxy\server.js"
```

Then create the config file `%USERPROFILE%\.claude\proxy\config.json`:

```json
{
  "port": 8082,
  "host": "127.0.0.1",
  "default_model": "claude-sonnet-4-6",
  "max_tokens": 8192
}
```

### 4. Make sure Claude Code is logged in

```cmd
claude --version
```

If this prints a version number, you're authenticated. If not, run `claude` and log in first.

---

## Running (every time)

You need **two terminal windows** plus your browser.

### Terminal 1 — Start the proxy

```cmd
node "%USERPROFILE%\.claude\proxy\server.js"
```

Wait until you see:

```
Claude proxy listening on http://127.0.0.1:8082
Token loaded, ready
```

### Terminal 2 — Start the agent

```cmd
cd remote-control-claude
python -m streamlit run app.py --server.port 8510
```

### Browser — Open the UI

Go to **http://localhost:8510**

The sidebar should show **"Proxy connected"** in green. If it shows red, check that Terminal 1 is running.

### AnyDesk / TeamViewer — Connect to your work PC

Open your remote desktop app, connect to the work computer, and go **full screen**.

### Chat — Tell Claude what to do

Type in the chat box:

```
Take a screenshot and describe what you see.
```

Claude will take a screenshot, see the remote desktop, and describe it. Then try:

```
Open Excel and create a new spreadsheet.
```

```
Open Chrome and go to google.com.
```

```
Find the file called "Report Q1" on the desktop and open it.
```

---

## Optional: Auto-start the proxy on login

So you don't have to start Terminal 1 every time.

Create this file: `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\claude-proxy.vbs`

```vbs
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "node " & CreateObject("WScript.Shell").ExpandEnvironmentStrings("%USERPROFILE%") & "\.claude\proxy\server.js", 0, False
```

The proxy will start silently when you log in.

---

## Multi-Monitor

If you have multiple monitors, Claude sees all of them in one screenshot. Put AnyDesk/TeamViewer on one monitor full-screen and tell Claude which side:

```
The right side of the screen is the remote desktop. Open Notepad on it.
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| **Sidebar shows "Proxy not running"** | Start the proxy: `node "%USERPROFILE%\.claude\proxy\server.js"` |
| **"Token refresh failed"** | Your Claude login expired. Run `claude` in a terminal to re-login, then restart the proxy |
| **Clicks land in wrong spot** | Lower the remote desktop resolution to 1024x768 in AnyDesk/TeamViewer settings |
| **Screenshots are black** | Disable hardware acceleration in your remote desktop app settings |
| **"unsupported operand type"** | Pull the latest code: `git pull` |
| **Streamlit won't start** | Port may be in use. Try: `python -m streamlit run app.py --server.port 8520` |

---

## Security

- **Watch what it does.** Don't leave the agent running unattended on sensitive systems.
- **Don't paste passwords** into the chat.
- The proxy runs on `127.0.0.1` only — nothing is exposed to the network.
- Uses your Claude subscription. Screenshots use tokens.

---

## How It Works (technical)

```
app.py (Streamlit UI)
    ↓ user types a task
agent.py
    ↓ takes screenshot with pyautogui / PIL
    ↓ sends screenshot + task to Claude API
    ↓ via local proxy (localhost:8082)
oauth-proxy.js
    ↓ reads OAuth token from ~/.claude/.credentials.json
    ↓ auto-refreshes expired tokens
    ↓ forwards request to api.anthropic.com
Claude responds with tool calls (click, type, scroll...)
    ↓
agent.py executes the actions with pyautogui
    ↓ takes another screenshot to verify
    ↓ loops until task is done
```
