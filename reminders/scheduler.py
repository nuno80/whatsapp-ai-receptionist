import logging
import re
from datetime import datetime, timedelta

import pytz

logger = logging.getLogger(__name__)


def extract_phone_from_description(description: str) -> str | None:
    match = re.search(r'Phone:\s*(\+?\d+)', description or "")
    return match.group(1) if match else None

def extract_language_from_description(description: str) -> str:
    match = re.search(r'Language:\s*([a-zA-Z]+)', description or "")
    return match.group(1).lower() if match else "it"


def format_reminder_message(event: dict, language: str) -> str:
    start_raw = event["start"].get("dateTime", "")
    try:
        dt = datetime.fromisoformat(start_raw)
        time_str = dt.strftime("%H:%M")
    except ValueError:
        time_str = start_raw

    # Simple blurb lookup, could move to knowledge/
    blurbs = {
        "en": "We look forward to seeing you. Let us know if you need directions.",
        "it": "Ti aspettiamo. Facci sapere se hai bisogno di indicazioni.",
        "es": "Te esperamos. Avísanos si necesitas indicaciones.",
    }
    blurb = blurbs.get(language, blurbs["it"])

    if language == "en":
        return f"Reminder: your check-in is tomorrow at {time_str}. {blurb}"
    elif language == "es":
        return f"Recordatorio: tu check-in es mañana a las {time_str}. {blurb}"
    else:
        return f"Promemoria: il tuo check-in è domani alle {time_str}. {blurb}"

async def send_reminders(config: dict, calendar_service, wa_client) -> int:
    """
    Query Calendar for events within the reminder window and send WhatsApp reminders.
    Returns number of reminders sent.
    """
    tz = pytz.timezone(config["client"].get("timezone", "Europe/Rome"))
    now = datetime.now(tz)
    hours_before = config.get("reminders", {}).get("hours_before", 48)
    
    window_start = now
    window_end = now + timedelta(hours=hours_before)

    calendar_id = config["booking"]["calendar_id"]
    events_result = calendar_service.events().list(
        calendarId=calendar_id,
        timeMin=window_start.isoformat(),
        timeMax=window_end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = events_result.get("items", [])
    sent = 0

    for event in events:
        description = event.get("description", "")
        # Pure OTA blocks get no reminder (no phone / tagged as OTA)
        if "OTA" in event.get("summary", "") and not extract_phone_from_description(description):
            continue

        phone = extract_phone_from_description(description)
        if not phone:
            logger.warning("No phone in event: %s", event.get("summary"))
            continue

        language = extract_language_from_description(description)
        msg = format_reminder_message(event, language)
        await wa_client.send_text(phone, msg)
        sent += 1
        logger.info("Reminder sent to %s for event %s (lang: %s)", phone, event.get("summary"), language)

    return sent
