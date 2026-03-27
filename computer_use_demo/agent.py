"""
Custom computer use agent loop that works with OAuth.

Instead of relying on Anthropic's computer-use beta tools (which require
API key auth), this agent uses Claude's vision capability to see the screen
and returns structured tool calls via a custom tool schema.

Flow:
1. Take screenshot with pyautogui
2. Send as image to Claude via OAuth proxy (regular messages API)
3. Claude responds with tool_use blocks (click, type, key, screenshot)
4. We execute those actions locally
5. Repeat
"""

import asyncio
import base64
import json
import os
import platform
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx
import pyautogui
from anthropic import Anthropic
from PIL import ImageGrab

# Multi-monitor support: capture the FULL virtual screen (all monitors)
# On single monitor this is identical to pyautogui.screenshot()
def _get_virtual_screen_bbox() -> tuple[int, int, int, int]:
    """Return (left, top, right, bottom) of the full virtual screen."""
    try:
        import win32api
        left = win32api.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
        top = win32api.GetSystemMetrics(77)    # SM_YVIRTUALSCREEN
        width = win32api.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
        height = win32api.GetSystemMetrics(79) # SM_CYVIRTUALSCREEN
        return (left, top, left + width, top + height)
    except ImportError:
        w, h = pyautogui.size()
        return (0, 0, w, h)

VIRTUAL_BBOX = _get_virtual_screen_bbox()
SCREEN_LEFT = VIRTUAL_BBOX[0]
SCREEN_TOP = VIRTUAL_BBOX[1]
SCREEN_WIDTH = int(os.getenv("WIDTH", 0)) or (VIRTUAL_BBOX[2] - VIRTUAL_BBOX[0])
SCREEN_HEIGHT = int(os.getenv("HEIGHT", 0)) or (VIRTUAL_BBOX[3] - VIRTUAL_BBOX[1])

# Scale to recommended resolution (maintains aspect ratio best we can)
SCALE_WIDTH = 1366 if SCREEN_WIDTH > 2000 else 1024
SCALE_HEIGHT = int(SCALE_WIDTH * SCREEN_HEIGHT / SCREEN_WIDTH)

SYSTEM_PROMPT = f"""You are a remote desktop control agent. You control a REMOTE WORK COMPUTER through a remote desktop application (AnyDesk or TeamViewer) running on the local machine.

WHAT YOU SEE:
- Your screenshots show the LOCAL machine's screen
- The remote desktop app (AnyDesk/TeamViewer) is running full-screen or as a window
- EVERYTHING you see inside that remote desktop window is the REMOTE computer
- You interact with the remote computer by clicking/typing inside that window
- The local taskbar, title bars, and AnyDesk/TeamViewer toolbars are NOT part of the remote computer

CURRENT SETUP:
- Local OS: Windows ({platform.machine()})
- Virtual screen: {SCREEN_WIDTH}x{SCREEN_HEIGHT} pixels
- Scaled to: {SCALE_WIDTH}x{SCALE_HEIGHT} for your coordinates
- Current date: {datetime.today().strftime('%A, %B %d, %Y')}
- Screenshots capture all monitors (multi-monitor supported)

REMOTE DESKTOP TIPS:
- AnyDesk toolbar is usually at the top center — avoid clicking on it unless asked
- TeamViewer toolbar is usually at the top — same rule
- If the remote desktop has its own taskbar, that's the one you should interact with
- Lag is normal — after clicking or typing, wait for the screenshot to confirm the action landed
- If an action doesn't seem to register, try clicking the remote desktop window first to ensure it has focus, then retry
- Double-check coordinates: the remote desktop area may not fill the entire screen

AVAILABLE ACTIONS (use the tools provided):
- screenshot: Capture the current screen
- click: Click at coordinates (x, y) with left/right/double click
- type_text: Type a string of text
- key_press: Press keyboard keys (e.g., "enter", "ctrl+c", "alt+tab")
- mouse_move: Move mouse to coordinates (x, y)
- scroll: Scroll up or down at current position

COORDINATE SYSTEM:
- All coordinates are in the {SCALE_WIDTH}x{SCALE_HEIGHT} scaled space
- (0, 0) is top-left, ({SCALE_WIDTH}, {SCALE_HEIGHT}) is bottom-right

WORKFLOW:
1. ALWAYS start by taking a screenshot to see the current state
2. Identify where the remote desktop window is on screen
3. Perform actions INSIDE the remote desktop area
4. After each significant action, take a screenshot to verify it worked
5. If something didn't work, click inside the remote desktop first (to ensure focus), then retry
6. Be precise with coordinates — click in the CENTER of UI elements
7. When typing, first click on the target input field
8. For keyboard shortcuts, use key_press with modifiers (e.g., "ctrl+a")
"""

TOOLS = [
    {
        "name": "screenshot",
        "description": "Take a screenshot of the current screen to see what's on it.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "click",
        "description": "Click at a position on the screen.",
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": f"X coordinate (0-{SCALE_WIDTH})"},
                "y": {"type": "integer", "description": f"Y coordinate (0-{SCALE_HEIGHT})"},
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "double"],
                    "description": "Which button to click (default: left)",
                },
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "type_text",
        "description": "Type text at the current cursor position.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to type"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "key_press",
        "description": "Press keyboard keys. For combos use '+' (e.g., 'ctrl+c', 'alt+tab', 'enter').",
        "input_schema": {
            "type": "object",
            "properties": {
                "keys": {"type": "string", "description": "Key(s) to press"},
            },
            "required": ["keys"],
        },
    },
    {
        "name": "mouse_move",
        "description": "Move mouse cursor to a position without clicking.",
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": f"X coordinate (0-{SCALE_WIDTH})"},
                "y": {"type": "integer", "description": f"Y coordinate (0-{SCALE_HEIGHT})"},
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "scroll",
        "description": "Scroll up or down at the current mouse position.",
        "input_schema": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["up", "down"],
                    "description": "Scroll direction",
                },
                "amount": {
                    "type": "integer",
                    "description": "Number of scroll clicks (default: 3)",
                },
            },
            "required": ["direction"],
        },
    },
]


def scale_to_screen(x: int, y: int) -> tuple[int, int]:
    """Convert from scaled coordinates to actual screen coordinates.

    Handles multi-monitor virtual screen offsets (monitors left of primary
    can have negative coordinates).
    """
    x, y = int(x), int(y)
    real_x = SCREEN_LEFT + int(x * SCREEN_WIDTH / SCALE_WIDTH)
    real_y = SCREEN_TOP + int(y * SCREEN_HEIGHT / SCALE_HEIGHT)
    return real_x, real_y


def take_screenshot() -> str:
    """Take a screenshot of ALL monitors and return base64 encoded PNG.

    Uses PIL.ImageGrab with the full virtual screen bounding box so that
    multi-monitor setups are captured in a single image.
    """
    import io

    screenshot = ImageGrab.grab(bbox=VIRTUAL_BBOX, all_screens=True)
    screenshot = screenshot.resize((SCALE_WIDTH, SCALE_HEIGHT))
    buf = io.BytesIO()
    screenshot.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def execute_tool(name: str, input_data: dict) -> dict:
    """Execute a tool action and return the result."""
    if name == "screenshot":
        img_b64 = take_screenshot()
        return {"type": "image", "base64": img_b64}

    elif name == "click":
        x, y = scale_to_screen(input_data["x"], input_data["y"])
        button = input_data.get("button", "left")
        if button == "double":
            pyautogui.doubleClick(x, y)
        elif button == "right":
            pyautogui.rightClick(x, y)
        else:
            pyautogui.click(x, y)
        return {"type": "text", "text": f"Clicked {button} at ({x}, {y})"}

    elif name == "type_text":
        text = input_data["text"]
        pyautogui.write(text, interval=0.02)
        return {"type": "text", "text": f"Typed: {text[:50]}{'...' if len(text) > 50 else ''}"}

    elif name == "key_press":
        keys = input_data["keys"]
        pyautogui.hotkey(*keys.split("+"))
        return {"type": "text", "text": f"Pressed: {keys}"}

    elif name == "mouse_move":
        x, y = scale_to_screen(input_data["x"], input_data["y"])
        pyautogui.moveTo(x, y)
        return {"type": "text", "text": f"Moved mouse to ({x}, {y})"}

    elif name == "scroll":
        direction = input_data["direction"]
        amount = input_data.get("amount", 3)
        clicks = amount if direction == "up" else -amount
        pyautogui.scroll(clicks)
        return {"type": "text", "text": f"Scrolled {direction} {amount} clicks"}

    return {"type": "text", "text": f"Unknown tool: {name}"}


async def agent_loop(
    *,
    user_message: str,
    model: str = "claude-sonnet-4-6",
    system_suffix: str = "",
    base_url: str | None = None,
    api_key: str = "proxy-handles-auth",
    max_turns: int = 20,
    output_callback: Callable | None = None,
    tool_callback: Callable | None = None,
) -> list[dict]:
    """
    Run the computer use agent loop.

    Returns the full message history.
    """
    if base_url is None:
        base_url = os.getenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:8082")

    client = Anthropic(api_key=api_key, base_url=base_url)

    system = SYSTEM_PROMPT
    if system_suffix:
        system += f"\n\n{system_suffix}"

    messages = [
        {"role": "user", "content": [{"type": "text", "text": user_message}]}
    ]

    for turn in range(max_turns):
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=system,
            tools=TOOLS,
            messages=messages,
        )

        # Process response
        assistant_content = []
        tool_results = []
        has_tool_use = False

        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
                if output_callback:
                    output_callback({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                has_tool_use = True
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
                if output_callback:
                    output_callback({
                        "type": "tool_use",
                        "name": block.name,
                        "input": block.input,
                    })

                # Execute the tool
                result = execute_tool(block.name, block.input)

                if result["type"] == "image":
                    tool_result_content = [
                        {"type": "text", "text": "Screenshot captured."},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": result["base64"],
                            },
                        },
                    ]
                else:
                    tool_result_content = [
                        {"type": "text", "text": result["text"]}
                    ]

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": tool_result_content,
                })

                if tool_callback:
                    tool_callback(block.name, result)

        messages.append({"role": "assistant", "content": assistant_content})

        if not has_tool_use:
            # Claude is done — no more tool calls
            break

        messages.append({"role": "user", "content": tool_results})

    return messages
