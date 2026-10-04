import json
import re

import streamlit as st
from google import genai
from google.genai import types

from prompts import SYSTEM_PROMPT, SUMMARY_REQUEST_PROMPT, WELCOME_MESSAGE_TEMPLATE

MODEL_NAME = "gemini-2.5-flash"


@st.cache_resource
def get_gemini_client():
    return genai.Client(api_key=st.secrets["GEMINI_API_KEY"])


@st.cache_resource
def get_twilio_client():
    """Reserved for the future WhatsApp integration; not used by this release."""
    from twilio.rest import Client as TwilioClient

    return TwilioClient(st.secrets["TWILIO_ACCOUNT_SID"], st.secrets["TWILIO_AUTH_TOKEN"])


def create_chat():
    return get_gemini_client().chats.create(
        model=MODEL_NAME,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
    )


def render_message(message):
    with st.chat_message(message["role"]):
        if message["kind"] == "image":
            st.image(message["content"])
        else:
            st.write(message["content"])


def add_message(role, kind, content):
    st.session_state.messages.append({"role": role, "kind": kind, "content": content})


def clean_whatsapp_text(text):
    return " ".join(text.replace("\r", " ").split())[:1500]


def _template_texts(value):
    """Yield all text fields from a Twilio Content template's type payload."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _template_texts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _template_texts(item)


def _content_variables(content_types, user_name, summary):
    """Build exactly the variable keys declared by the selected Content template."""
    keys = []
    for template_text in _template_texts(content_types):
        for key in re.findall(r"{{\s*([^{}]+?)\s*}}", template_text):
            if key not in keys:
                keys.append(key)

    if not keys:
        return None

    # The Try out WhatsApp templates commonly use {{1}} and {{2}}. If a
    # supplied trial template has one placeholder, it receives the summary.
    values = {}
    for index, key in enumerate(keys):
        values[key] = clean_whatsapp_text(summary) if len(keys) == 1 or index else user_name
        if index and len(keys) > 1:
            values[key] = clean_whatsapp_text(summary)
    return json.dumps(values, ensure_ascii=False)


def send_whatsapp(to_number, user_name, summary):
    """Reserved for the future WhatsApp integration; not called by this release."""
    twilio_client = get_twilio_client()
    content_sid = st.secrets["TWILIO_CONTENT_SID"]
    content = twilio_client.content.v1.contents(content_sid).fetch()
    message_options = {
        "from_": st.secrets["TWILIO_WHATSAPP_FROM"],
        "to": f"whatsapp:{to_number}",
        "content_sid": content_sid,
    }
    content_variables = _content_variables(content.types, user_name, summary)
    if content_variables is not None:
        message_options["content_variables"] = content_variables
    return twilio_client.messages.create(**message_options)


def has_discussion():
    return any(message["role"] == "user" for message in st.session_state.messages)


st.set_page_config(page_title="MacroSnap", page_icon="🥗")

if "onboarded" not in st.session_state:
    st.title("🥗 MacroSnap")
    st.write("Get quick, approximate nutrition estimates for meals and meal photos.")
    with st.form("onboarding"):
        name = st.text_input("Your name")
        whatsapp_number = st.text_input("WhatsApp number", placeholder="+91XXXXXXXXXX")
        submitted = st.form_submit_button("Start chatting")
    if submitted:
        if not name.strip() or not whatsapp_number.strip():
            st.error("Please enter both your name and WhatsApp number.")
        elif not whatsapp_number.strip().startswith("+"):
            st.error("Use an international WhatsApp number, for example +91XXXXXXXXXX.")
        else:
            try:
                st.session_state.name = name.strip()
                st.session_state.whatsapp_number = whatsapp_number.strip()
                st.session_state.messages = []
                st.session_state.chat = create_chat()
                st.session_state.onboarded = True
                st.rerun()
            except Exception:
                st.error("I couldn't connect to Gemini. Check your API key and try again.")
    st.stop()

if "chat" not in st.session_state:
    try:
        st.session_state.chat = create_chat()
    except Exception:
        st.error("I couldn't start Gemini. Check your configuration and refresh the page.")
        st.stop()

if not st.session_state.messages:
    add_message("assistant", "text", WELCOME_MESSAGE_TEMPLATE.format(name=st.session_state.name))

st.title("🥗 MacroSnap")
st.caption(f"Logged in as {st.session_state.name}")

for message in st.session_state.messages:
    render_message(message)

# WhatsApp sending is intentionally disabled for this Community Cloud release.
# The helpers above are retained for a future Twilio Content API integration.

prompt = st.chat_input(
    "Ask a question or attach a meal photo",
    accept_file=True,
    file_type=["jpg", "jpeg", "png"],
)

if prompt:
    text = getattr(prompt, "text", prompt if isinstance(prompt, str) else "").strip()
    photos = list(getattr(prompt, "files", []))
    with st.chat_message("user"):
        for photo in photos:
            image_bytes = photo.getvalue()
            st.image(image_bytes)
            add_message("user", "image", image_bytes)
        if text:
            st.write(text)
            add_message("user", "text", text)

    if text or photos:
        parts = [types.Part.from_bytes(data=p.getvalue(), mime_type=p.type) for p in photos]
        if text:
            parts.append(types.Part.from_text(text=text))
        elif photos:
            parts.append(types.Part.from_text(text="What is this meal? Estimate its calories, protein, carbs and fat."))
        try:
            with st.chat_message("assistant"):
                with st.spinner("Analyzing your meal..."):
                    response = st.session_state.chat.send_message(parts)
                    answer = response.text
                st.write(answer)
            add_message("assistant", "text", answer)
        except Exception:
            st.error("I couldn't analyze that just now. Please try again in a moment.")

st.caption("WhatsApp integration is planned for the next version.")
