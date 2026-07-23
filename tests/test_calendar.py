# tests/test_calendar.py
import pytest
from datetime import date, time
from unittest.mock import MagicMock, patch
from modules.booking.calendar import CalendarClient

def make_client():
    with patch("modules.booking.calendar._get_credentials") as mock_creds, \
         patch("modules.booking.calendar.build") as mock_build:
        mock_creds.return_value = MagicMock()
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        client = CalendarClient(
            calendar_id="test@calendar",
            calendar_owner_email="owner@gmail.com",
            timezone="Europe/Rome"
        )
        client._service = mock_service
        return client, mock_service

def test_is_range_available_free(monkeypatch):
    client, mock_service = make_client()
    mock_service.freebusy().query().execute.return_value = {
        "calendars": {"test@calendar": {"busy": []}}
    }
    monkeypatch.setattr("modules.booking.calendar._get_redis", lambda: None)
    result = client.is_range_available(date(2026, 3, 16), date(2026, 3, 18))
    assert result is True
    
    # Check that freebusy queried the whole range
    call_args = mock_service.freebusy().query.call_args[1]["body"]
    assert call_args["timeMin"] == "2026-03-16T15:00:00+01:00"  # assuming 15:00 checkin
    assert call_args["timeMax"] == "2026-03-18T10:00:00+01:00"  # assuming 10:00 checkout

def test_is_range_available_busy(monkeypatch):
    client, mock_service = make_client()
    mock_service.freebusy().query().execute.return_value = {
        "calendars": {"test@calendar": {"busy": [
            {"start": "2026-03-17T15:00:00+01:00", "end": "2026-03-19T10:00:00+01:00"}
        ]}}
    }
    monkeypatch.setattr("modules.booking.calendar._get_redis", lambda: None)
    result = client.is_range_available(date(2026, 3, 16), date(2026, 3, 18))
    assert result is False

def test_is_range_available_soft_locked(monkeypatch):
    client, mock_service = make_client()
    mock_service.freebusy().query().execute.return_value = {
        "calendars": {"test@calendar": {"busy": []}}
    }
    
    mock_redis = MagicMock()
    # Mock redis keys: one lock overlaps
    mock_redis.keys.return_value = [b"range_lock:2026-03-17:2026-03-19"]
    monkeypatch.setattr("modules.booking.calendar._get_redis", lambda: mock_redis)
    
    result = client.is_range_available(date(2026, 3, 16), date(2026, 3, 18))
    assert result is False

def test_soft_lock_and_release(monkeypatch):
    client, _ = make_client()
    mock_redis = MagicMock()
    monkeypatch.setattr("modules.booking.calendar._get_redis", lambda: mock_redis)
    
    client.lock_range(date(2026, 3, 16), date(2026, 3, 18))
    mock_redis.set.assert_called_with("range_lock:2026-03-16:2026-03-18", "1", ex=86400)
    
    client.release_range(date(2026, 3, 16), date(2026, 3, 18))
    mock_redis.delete.assert_called_with("range_lock:2026-03-16:2026-03-18")

def test_create_event(monkeypatch):
    client, mock_service = make_client()
    mock_service.events().insert().execute.return_value = {"id": "event123"}
    
    event_id = client.create_event(
        checkin_date=date(2026, 3, 16),
        checkout_date=date(2026, 3, 18),
        guest_name="Jane Smith",
        guest_phone="393331234567",
        guests_count=2,
        total_price=200,
        language="it",
        payment_state="pending",
        request_id="req-123"
    )
    assert event_id == "event123"
    
    call_args = mock_service.events().insert.call_args[1]["body"]
    assert "Jane Smith" in call_args["summary"]
    assert call_args["start"]["dateTime"] == "2026-03-16T15:00:00+01:00"
    assert call_args["end"]["dateTime"] == "2026-03-18T10:00:00+01:00"
    desc = call_args["description"]
    assert "393331234567" in desc
    assert "req-123" in desc
    assert "200" in desc
    assert "pending" in desc
