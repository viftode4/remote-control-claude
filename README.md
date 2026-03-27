# Remote Control Agent

AI-powered desktop automation that uses Claude to control a remote computer through AnyDesk, TeamViewer, or any remote desktop software. Uses your existing Claude subscription via OAuth -- no API key needed.

## How It Works

```
Your PC                          Remote Work PC
┌─────────────────┐              ┌──────────────┐
│  Agent (Python)  │──AnyDesk───▶│  (no install  │
│  takes screenshot│  TeamViewer │   needed)     │
│  sends to Claude │              └──────────────┘
│  executes clicks │
│  types text      │
└────────┬────────┘
         │ OAuth
         ▼
   Claude API (via local proxy)
```

Claude sees your screen as a screenshot, decides what to click/type/scroll, and the agent executes those actions. When a remote desktop is open full-screen, Claude controls the remote machine through it.

**Nothing gets installed on the remote computer.**

## Prerequisites

- **Windows 10+** with Python 3.10-3.13
- **Claude Code** installed and logged in (`claude` command works in your terminal)
- **AnyDesk / TeamViewer** or any remote desktop app

That's it. The agent uses your Claude Code login -- the same OAuth token that powers `claude` in your terminal.

## Setup (5 minutes)

### Step 1: Clone and install

```cmd
git clone https://github.com/viftode4/remote-control-claude.git
cd remote-control-claude
pip install -r requirements.txt
```

### Step 2: Verify Claude Code is logged in

```cmd
claude --version
```

If this works, you're authenticated. The agent reads your OAuth token from `~/.claude/.credentials.json` automatically.

### Step 3: Start the OAuth proxy

The proxy reads your Claude Code credentials and handles token refresh automatically.

```cmd
node %USERPROFILE%\.claude\proxy\server.js
```

You should see:
```
Claude proxy listening on http://127.0.0.1:8082
Token loaded, ready
```

> **Don't have the proxy?** See [Proxy Setup](#proxy-setup) below to install it.

### Step 4: Start the agent

```cmd
python -m streamlit run app.py
```

### Step 5: Open the UI

Go to **http://localhost:8510** in your browser.

### Step 6: Use it

1. Open AnyDesk/TeamViewer and connect to your remote work PC
2. Set the remote desktop to **full screen**
3. In the agent chat, tell Claude what to do:

```
Take a screenshot and describe what you see.
```

```
Open the Excel file on the desktop, go to Sheet2, and copy the table.
```

```
Open Chrome, go to our internal wiki, and find the IT support phone number.
```

Claude will take screenshots, click, type, and scroll to complete the task.

## Proxy Setup

If you don't already have the OAuth proxy, set it up:

### 1. Create the proxy directory

```cmd
mkdir %USERPROFILE%\.claude\proxy
```

### 2. Install Node.js

Download from https://nodejs.org if you don't have it.

### 3. Copy the proxy file

Copy `proxy/oauth-proxy.js` from this repo to `%USERPROFILE%\.claude\proxy\server.js`.

Or create it manually -- the proxy is a single file that:
- Reads OAuth credentials from `~/.claude/.credentials.json`
- Refreshes tokens automatically via `console.anthropic.com`
- Forwards requests to `api.anthropic.com` with the OAuth Bearer token
- Listens on `http://127.0.0.1:8082`

### 4. Create config

Create `%USERPROFILE%\.claude\proxy\config.json`:

```json
{
  "port": 8082,
  "host": "127.0.0.1",
  "default_model": "claude-sonnet-4-6",
  "max_tokens": 8192
}
```

### 5. Auto-start (optional)

To start the proxy automatically on login, create a file at:

```
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\claude-proxy.vbs
```

With this content:

```vbs
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "node C:\Users\YOUR_USERNAME\.claude\proxy\server.js", 0, False
```

Replace `YOUR_USERNAME` with your Windows username.

## What Can It Do?

| Action | How |
|--------|-----|
| See the screen | Takes screenshots via `pyautogui` |
| Click | Left click, right click, double click at any position |
| Type text | Types strings character by character |
| Keyboard shortcuts | `ctrl+c`, `alt+tab`, `enter`, etc. |
| Scroll | Scroll up/down |
| Move mouse | Move cursor without clicking |

Claude decides which actions to take based on what it sees in the screenshot. It works exactly like a person sitting at your desk using your mouse and keyboard.

## Multi-Monitor Support

The agent captures **all monitors** in a single screenshot. If you have two monitors, Claude sees both side by side and can click on either one.

```
┌──────────────┐┌──────────────┐
│  Monitor 1   ││  Monitor 2   │    ← Claude sees ALL of this
│  (primary)   ││ (AnyDesk)    │       as one wide screenshot
└──────────────┘└──────────────┘
```

**Recommended setup:** Put AnyDesk/TeamViewer on one monitor in full screen. Claude will see it and know to interact with that monitor. You can tell it explicitly:

> "The right side of the screen is an AnyDesk session. Click on the desktop icon labeled 'Reports'."

If you only want Claude to see one monitor, set `WIDTH` and `HEIGHT` in `.env` to that monitor's resolution.

## Tips for Best Results

- **Full screen** your remote desktop app -- less noise for Claude to parse
- **"Optimize speed"** in AnyDesk/TeamViewer settings -- cleaner screenshots
- **Be specific** in your prompts -- "Click the Save button in the top-right" is better than "save it"
- **Lower remote resolution** to 1024x768 if possible -- Claude's sweet spot
- **Watch it work** -- the agent shows screenshots and actions in real time
- **Multi-monitor:** Claude captures all screens. Tell it which monitor to focus on if needed

## Project Structure

```
remote-control-claude/
├── app.py                       # Main UI (Streamlit)
├── computer_use_demo/
│   ├── agent.py                 # Agent loop (screenshot → Claude → actions)
│   ├── loop.py                  # Alternative loop (for API key auth)
│   └── tools/                   # pyautogui wrappers
├── proxy/
│   └── server.py                # Python proxy (alternative to Node proxy)
├── requirements.txt
├── setup.bat
└── .env.example
```

## Security

- **Supervise the agent.** Claude can be influenced by text on web pages (prompt injection). Don't leave it running unattended on sensitive systems.
- **Don't give it credentials.** Never paste passwords into the chat or let it access login screens unsupervised.
- The OAuth token stays local. The proxy runs on `127.0.0.1` and doesn't expose anything to the network.
- Your Claude subscription usage applies. Screenshots are token-intensive.

## Troubleshooting

**"Port 8082 refused"** -- The proxy isn't running. Start it with `node %USERPROFILE%\.claude\proxy\server.js`.

**"Token refresh failed"** -- Your Claude Code session expired. Run `claude` in a terminal to re-authenticate, then restart the proxy.

**"Agent not clicking accurately"** -- Lower your remote desktop resolution to 1024x768. High resolutions get scaled down and lose precision.

**Screenshots are blank/black** -- Some remote desktop apps use hardware acceleration that blocks screen capture. Try disabling GPU acceleration in AnyDesk/TeamViewer settings.

## Credits

Built on [Anthropic Computer Use](https://docs.anthropic.com/en/docs/build-with-claude/computer-use) concepts and the [Windows adaptation](https://github.com/sunkencity999/windows_claude_computer_use) by Christopher Bradford.
