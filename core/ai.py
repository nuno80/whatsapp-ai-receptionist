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
        content = Path(path).read_text(encoding="utf-8").strip()
        if content:
            return content
        # Empty file — treat as missing
        raise FileNotFoundError(path)
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

        # Build pricing summary for Claude
        pricing_lines = []
        for p in booking.get("pricing_periods", []):
            dow = p.get("days_of_week")
            day_names = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
            if dow:
                days = ", ".join(day_names.get(d, str(d)) for d in dow)
                pricing_lines.append(f"- {p['start_date']} to {p['end_date']} ({days}): €{p['price_per_night']}/night")
            else:
                pricing_lines.append(f"- {p['start_date']} to {p['end_date']}: €{p['price_per_night']}/night")
        pricing_text = "\n".join(pricing_lines) if pricing_lines else "See knowledge base."

        min_stay = booking.get("minimum_stay_periods", [])
        min_stay_text = ", ".join(f"{m['start_date']} to {m['end_date']}: {m['min_nights']} nights" for m in min_stay) if min_stay else "None"

        lines += [
            "",
            "BOOKINGS (STAYS):",
            today_str,
            f"Check-in: {booking.get('checkin_time', '15:00')}, Check-out: {booking.get('checkout_time', '10:00')}",
            f"Max guests: {booking.get('max_guests', 2)}",
            f"Minimum stay: {min_stay_text}",
            "",
            f"PRICING (last matching rule wins, day-of-week rules override base):\n{pricing_text}",
            "When the guest asks about price, calculate the total based on these rules and tell them.",
            "",
            f"Pre-calculated free dates for stays:\n{ranges_text}",
            "IMPORTANT: ONLY offer dates that fall completely within the pre-calculated free dates above. Do not merge disjoint date ranges in your responses.",
            "",
            "To book a stay, you need:",
            "1. Check-in date",
            "2. Check-out date",
            "3. Number of guests",
            "4. Full name",
            "",
            "IMPORTANT about the booking experience:",
            "- Try to complete the booking in as few messages as possible, but ask one thing per message.",
            "- Once you have ALL 4 data points (dates, guests, name), show a RECAP with the total price",
            "  and ask the guest to CONFIRM before proceeding. Example:",
            "  'Riepilogo: dal 5 al 10 agosto, 2 ospiti, a nome Mario Rossi. Totale: €XXX. Confermi?'",
            "- ONLY after the guest explicitly confirms (sì, ok, confermo, va bene, perfetto, etc.),",
            "  respond with the confirmation message AND include the JSON below.",
            "- If the guest says no, asks to change something, or says it's too expensive, do NOT emit the JSON.",
            "- Once the guest confirms, respond with the confirmation message",
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
