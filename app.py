"""
Remote Control Agent — Streamlit UI

Uses the OAuth-compatible agent loop to control the screen.
Connects to the local proxy at localhost:8082 (no API key needed).
"""

import asyncio
import base64
import os

import streamlit as st

from computer_use_demo.agent import agent_loop, take_screenshot

st.set_page_config(page_title="Remote Control Agent", layout="wide")

STYLE = """
<style>
    .stApp[data-teststate=running] .stChatInput textarea,
    .stApp[data-test-script-state=running] .stChatInput textarea {
        display: none;
    }
    .stAppDeployButton { visibility: hidden; }
</style>
"""


def setup():
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = []


def render_messages():
    for msg in st.session_state.messages:
        role = msg["role"]
        with st.chat_message(role):
            if msg.get("image"):
                st.image(base64.b64decode(msg["image"]))
            if msg.get("text"):
                st.markdown(msg["text"])
            if msg.get("action"):
                st.code(msg["action"])


async def run_agent(user_text: str):
    """Run the agent and collect results for display."""
    proxy_url = st.session_state.get(
        "proxy_url", os.getenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:8082")
    )
    model = st.session_state.get("model", "claude-sonnet-4-6")

    display_messages = st.session_state.messages
    status = st.empty()

    def on_output(block):
        if block.get("type") == "text":
            display_messages.append({"role": "assistant", "text": block["text"]})
        elif block.get("type") == "tool_use":
            action_str = f'{block["name"]}({block.get("input", {})})'
            display_messages.append({"role": "assistant", "action": action_str})

    def on_tool(name, result):
        if result["type"] == "image":
            display_messages.append(
                {"role": "assistant", "text": "Screenshot captured:", "image": result["base64"]}
            )
        else:
            display_messages.append({"role": "assistant", "text": f"*{result['text']}*"})

    status.info("Agent is running...")

    agent_msgs = await agent_loop(
        user_message=user_text,
        model=model,
        base_url=proxy_url,
        api_key="proxy-handles-auth",
        max_turns=int(st.session_state.get("max_turns", 15)),
        output_callback=on_output,
        tool_callback=on_tool,
    )

    st.session_state.agent_messages = agent_msgs
    status.empty()


def main():
    setup()
    st.markdown(STYLE, unsafe_allow_html=True)

    st.title("Remote Control Agent")
    st.caption("AI-powered screen control via OAuth — no API key needed")

    with st.sidebar:
        st.header("Settings")

        st.text_input(
            "Proxy URL",
            value=os.getenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:8082"),
            key="proxy_url",
            help="Local OAuth proxy URL",
        )
        st.text_input(
            "Model",
            value="claude-sonnet-4-6",
            key="model",
        )
        st.slider(
            "Max turns",
            min_value=1,
            max_value=30,
            value=15,
            key="max_turns",
            help="Maximum number of agent action loops",
        )

        # Quick screenshot preview
        if st.button("Preview Screenshot"):
            img = take_screenshot()
            st.image(base64.b64decode(base64.b64encode(
                base64.b64decode(img)
            )))

        if st.button("Clear Chat", type="secondary"):
            st.session_state.messages = []
            st.session_state.agent_messages = []
            st.rerun()

        st.divider()
        st.markdown(
            "**How to use:**\n"
            "1. Open AnyDesk/TeamViewer full-screen\n"
            "2. Tell Claude what to do\n"
            "3. Watch it work"
        )

    # Render chat history
    render_messages()

    # Chat input
    user_input = st.chat_input("Tell Claude what to do on the screen...")

    if user_input:
        st.session_state.messages.append({"role": "user", "text": user_input})

        with st.chat_message("user"):
            st.markdown(user_input)

        with st.spinner("Agent working..."):
            asyncio.run(run_agent(user_input))

        st.rerun()


if __name__ == "__main__":
    main()
