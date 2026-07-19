import pytest
from datetime import datetime, timedelta
import pytz
from unittest.mock import AsyncMock, MagicMock
from reminders.scheduler import (
    extract_phone_from_description,
    extract_language_from_description,
    format_reminder_message,
    send_reminders,
)


def make_mock_event(summary, description, start_datetime, location="456 Oak Avenue, Springfield"):
    return {
        "summary": summary,
        "description": description,
        "location": location,
        "start": {"dateTime": start_datetime},
    }


def test_extract_phone_from_description():
    desc = "Service: Stay\nPrice: $150\nPhone: +5491112345678\nPolicy: 24 hours"
    assert extract_phone_from_description(desc) == "+5491112345678"

def test_extract_language_from_description():
    desc = "Phone: +123\nLanguage: EN\nGuests: 2"
    assert extract_language_from_description(desc) == "en"

def test_extract_language_default():
    assert extract_language_from_description("Phone: +123") == "it"


def test_extract_phone_missing():
    assert extract_phone_from_description("No phone here") is None


def test_format_reminder_message():
    event = make_mock_event(
        "Stay - Jane",
        "Phone: 5491112345678",
        "2026-03-17T15:00:00+01:00",
    )
    msg = format_reminder_message(event, "en")
    assert "15:00" in msg
    assert "directions" in msg

    msg_it = format_reminder_message(event, "it")
    assert "15:00" in msg_it
    assert "indicazioni" in msg_it


@pytest.mark.asyncio
async def test_send_reminders_sends_message_for_each_event():
    config = {
        "client": {"timezone": "Europe/Rome"},
        "booking": {"calendar_id": "test@calendar"},
        "reminders": {"hours_before": 48},
    }

    mock_service = MagicMock()
    tz = pytz.timezone("Europe/Rome")
    start_dt = datetime.now(tz) + timedelta(hours=24)

    mock_service.events().list().execute.return_value = {
        "items": [
            make_mock_event(
                "Stay - Jane",
                "Phone: 5491112345678\nLanguage: en",
                start_dt.isoformat(),
            )
        ]
    }

    mock_wa = MagicMock()
    mock_wa.send_text = AsyncMock()

    count = await send_reminders(config, mock_service, mock_wa)
    assert count == 1
    mock_wa.send_text.assert_called_once()
    call_phone = mock_wa.send_text.call_args[0][0]
    call_msg = mock_wa.send_text.call_args[0][1]
    assert call_phone == "5491112345678"
    assert "directions" in call_msg


@pytest.mark.asyncio
async def test_send_reminders_skips_event_without_phone():
    config = {
        "client": {"timezone": "Europe/Rome"},
        "booking": {"calendar_id": "test@calendar"},
        "reminders": {"hours_before": 48},
    }

    mock_service = MagicMock()
    tz = pytz.timezone("Europe/Rome")
    start_dt = datetime.now(tz) + timedelta(hours=24)

    mock_service.events().list().execute.return_value = {
        "items": [
            make_mock_event("Stay - OTA", "OTA booking, no phone", start_dt.isoformat())
        ]
    }

    mock_wa = MagicMock()
    mock_wa.send_text = AsyncMock()

    count = await send_reminders(config, mock_service, mock_wa)
    assert count == 0
    mock_wa.send_text.assert_not_called()
