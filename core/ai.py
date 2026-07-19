import json
import logging
import os
import re
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

MODEL = "claude-3-5-sonnet-20240620"
MAX_TOKENS = 1024

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
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
        f"Respond in this language code: {detected_lang}.",
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
    pattern = re.compile(r'\{[^{}]*"intent"\s*:\s*"[^"]*"[^{}]*\}', re.DOTALL)
    match = pattern.search(response)
    if not match:
        return None, response
    try:
        intent = json.loads(match.group())
    except json.JSONDecodeError:
        return None, response
    visible = response[:match.start()].strip()
    # Remove any trailing markdown code fences that Claude might add
    visible = re.sub(r'```\s*json\s*$', '', visible, flags=re.MULTILINE).strip()
    visible = re.sub(r'```\s*$', '', visible, flags=re.MULTILINE).strip()
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
    resp = get_client().messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=messages,
    )
    return resp.content[0].text
