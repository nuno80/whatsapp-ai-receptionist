import json
import logging
import os
import re
from pathlib import Path

import anthropic
import openai

logger = logging.getLogger(__name__)

MAX_TOKENS = 1024

# ponytail: single `if` on env, no Provider base class. Add abstractions when a 3rd provider lands.
_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").lower()

def _anthropic_default_model() -> str:
    return os.environ.get("LLM_MODEL", "claude-3-5-sonnet-20241022")

def _nvidia_default_model() -> str:
    # If the base URL is Groq, default to Groq's llama model
    base = os.environ.get("LLM_BASE_URL", "")
    if "groq.com" in base:
        return os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")
    return os.environ.get("LLM_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")

def _model() -> str:
    return _anthropic_default_model() if _PROVIDER == "anthropic" else _nvidia_default_model()

# Backward-compat: external code/tests imported `MODEL`. Reflects the active provider's model.
MODEL = _model()

_client: anthropic.Anthropic | openai.OpenAI | None = None


def _require_env(name: str) -> str:
    try:
        return os.environ[name]
    except KeyError:
        raise RuntimeError(f"Missing required env var '{name}' for LLM_PROVIDER='{_PROVIDER}'.")


def get_client() -> anthropic.Anthropic | openai.OpenAI:
    global _client
    if _client is None:
        if _PROVIDER == "anthropic":
            _client = anthropic.Anthropic(api_key=_require_env("ANTHROPIC_API_KEY"))
        else:
            _client = openai.OpenAI(
                base_url=os.environ.get("LLM_BASE_URL", "https://integrate.api.nvidia.com/v1"),
                api_key=_require_env("LLM_API_KEY") if os.environ.get("LLM_API_KEY") else _require_env("NVIDIA_API_KEY"),
            )
    return _client


def load_knowledge(lang: str = "it") -> str:
    path = f"knowledge/{lang}.txt"
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        if lang != "it":
            logger.warning("Knowledge file not found for %s, falling back to 'it'.", lang)
            return load_knowledge("it")
        logger.warning("Knowledge file not found: %s", path)
        return ""


def build_system_prompt(config: dict, knowledge: str, free_ranges: list[dict] = None, detected_lang: str = "it") -> str:
    client_name = config["client"]["name"]
    modules = config.get("modules", {})
    persona = config.get("bot_persona", {})
    name = persona.get("name", "Giulia")
    tone = persona.get("tone", "cordiale-professionale")
    is_ai = persona.get("declares_as_ai", True)

    lines = [
        f"You are {name}, the virtual assistant for {client_name}.",
        f"Tone: {tone}.",
        "Speak in the first person as the assistant, never impersonate a human host.",
        "FORMAT: Use WhatsApp formatting only. Bold with *single asterisks* (not **double**). Italics with _underscores_. No markdown headings, no #, no ``` or backticks.",
        f"Respond in this language code: {detected_lang} (IT/EN/ES/FR/DE). DO NOT machine-translate.",
        "Be concise (maximum 3-4 paragraphs). Do not use emojis unless appropriate for the tone.",
    ]

    if is_ai:
        lines.append("Explicitly state you are a virtual assistant (not a human host) early in the conversation and if asked.")

    lines += [
        "",
        "KNOWLEDGE BASE:",
        knowledge,
    ]

    if modules.get("booking"):
        booking = config.get("booking", {})
        from datetime import date as date_cls
        today_str = f"Today is {date_cls.today().isoformat()}."

        ranges_text = "None"
        if free_ranges:
            ranges_text = "\n".join([f"- From {r['start']} to {r['end']}" for r in free_ranges])

        lines += [
            "",
            "BOOKINGS (STAYS):",
            today_str,
            f"Pre-calculated free dates for stays:\n{ranges_text}",
            "IMPORTANT: ONLY offer dates that fall within the pre-calculated free dates above. The server validation always wins.",
            "",
            "To book a stay, you need:",
            "1. Check-in date",
            "2. Check-out date",
            "3. Number of guests",
            "4. Full name",
            "",
            "IMPORTANT about the booking experience:",
            "- Try to complete the booking in as few messages as possible, but ask one thing per message.",
            "- Once you have all data confirmed, respond with a confirmation message",
            "AND at the end include this JSON on a single line:",
            '{"intent": "booking_requested", "checkin": "<YYYY-MM-DD>", "checkout": "<YYYY-MM-DD>", '
            '"guests": <number>, "user_name": "<full name>", "lang": "<language code>"}',
            "IMPORTANT: Use 'booking_requested' (never claim the booking is confirmed, it requires human approval).",
            "IMPORTANT: The JSON goes in plain text at the end, never inside code blocks.",
            "",
            "CANCELLATIONS:",
            "When the user wants to cancel their stay, respond politely and at the end include:",
            '{"intent": "cancellation_request"}',
            "If the system shows their bookings and the user confirms which one to cancel, respond with:",
            '{"intent": "cancellation_confirmed", "event_index": <number>}',
            "",
            "MODIFICATIONS:",
            "When the user wants to change dates, ALWAYS respond with:",
            '{"intent": "modification_request"}',
            "When the user confirms the new dates for a modified stay, emit a booking_requested JSON with the new checkin/checkout."
        ]

    return "\n".join(lines)


def extract_intent(response: str) -> tuple[dict | None, str]:
    """
    Look for any intent JSON block in Claude's response.
    Returns (intent_dict, visible_text) — strips the JSON from user-visible text.
    """
    # NVIDIA-compatible models wrap intent JSON in ```json fences more often than Claude.
    search_target = re.sub(r'```(?:json)?\s*', '', response)
    pattern = re.compile(r'\{[^{}]*"intent"\s*:\s*"[^"]*"[^{}]*\}', re.DOTALL)
    match = pattern.search(search_target)
    if not match:
        return None, response
    try:
        intent = json.loads(match.group())
    except json.JSONDecodeError:
        return None, response
    # Strip the matched region (and any surrounding fence space) from the visible text.
    visible = response[:response.find(match.group())].strip()
    visible = re.sub(r'```\s*(json)?\s*$', '', visible, flags=re.MULTILINE).strip()
    return intent, visible


# Keep backward compatibility
extract_booking_intent = extract_intent


def get_ai_response(
    user_message: str,
    history: list[dict],
    config: dict,
    knowledge: str,
    free_ranges: list[dict] = None,
    detected_lang: str = "it"
) -> str:
    system_prompt = build_system_prompt(config, knowledge, free_ranges, detected_lang)
    messages = history + [{"role": "user", "content": user_message}]
    client = get_client()
    model = _model()
    if _PROVIDER == "anthropic":
        resp = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=messages,
        )
        return resp.content[0].text
    # OpenAI-compatible path (NVIDIA NIM and others via LLM_BASE_URL)
    openai_messages = [{"role": "system", "content": system_prompt}] + messages
    resp = client.chat.completions.create(
        model=model,
        max_tokens=MAX_TOKENS,
        temperature=1,
        messages=openai_messages,
    )
    return resp.choices[0].message.content or ""
