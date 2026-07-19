import pytest
import os
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import date, datetime

from modules.booking.ota_sync import sync_ota, parse_ical_ranges

@pytest.fixture
def mock_config():
    return {
        "modules": {"ota_sync": True},
        "ota": {"ical_urls": ["http://example.com/cal.ics"]}
    }

@pytest.fixture
def mock_calendar_client():
    import pytz
    client = MagicMock()
    client._tz = pytz.UTC
    client._calendar_id = "test_cal"
    return client

def test_parse_ical_ranges():
    ics_data = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//ZContent.net//Zap Calendar 1.0//EN
CALSCALE:GREGORIAN
METHOD:PUBLISH
BEGIN:VEVENT
SUMMARY:Reserved
UID:12345
DTSTART;VALUE=DATE:20261010
DTEND;VALUE=DATE:20261015
END:VEVENT
END:VCALENDAR"""
    
    blocks = parse_ical_ranges(ics_data)
    assert len(blocks) == 1
    assert blocks[0] == (date(2026, 10, 10), date(2026, 10, 15), "12345")

@pytest.mark.asyncio
async def test_sync_ota_no_op_when_disabled(mock_calendar_client):
    config = {"modules": {"ota_sync": False}}
    await sync_ota(config, mock_calendar_client)
    mock_calendar_client._service.events().list.assert_not_called()

@pytest.mark.asyncio
async def test_sync_ota_empty_urls(mock_calendar_client):
    config = {"modules": {"ota_sync": True}, "ota": {"ical_urls": []}}
    await sync_ota(config, mock_calendar_client)
    mock_calendar_client._service.events().list.assert_not_called()

@pytest.mark.asyncio
@patch("urllib.request.urlopen")
async def test_sync_ota_inserts_events(mock_urlopen, mock_config, mock_calendar_client):
    ics_data = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:test-uid-1
DTSTART;VALUE=DATE:20301010
DTEND;VALUE=DATE:20301015
END:VEVENT
END:VCALENDAR"""
    
    mock_response = MagicMock()
    mock_response.read.return_value = ics_data
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response
    
    # Mock existing events list
    mock_list_req = MagicMock()
    mock_list_req.execute.return_value = {"items": []}
    mock_calendar_client._service.events().list.return_value = mock_list_req
    
    mock_insert_req = MagicMock()
    mock_calendar_client._service.events().insert.return_value = mock_insert_req

    await sync_ota(mock_config, mock_calendar_client)
    
    mock_calendar_client._service.events().insert.assert_called_once()
    call_args = mock_calendar_client._service.events().insert.call_args[1]
    assert call_args["calendarId"] == "test_cal"
    assert "ota:test-uid-1" in call_args["body"]["description"]

@pytest.mark.asyncio
@patch("urllib.request.urlopen")
async def test_sync_ota_skips_existing(mock_urlopen, mock_config, mock_calendar_client):
    ics_data = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:existing-uid
DTSTART;VALUE=DATE:20301010
DTEND;VALUE=DATE:20301015
END:VEVENT
END:VCALENDAR"""
    
    mock_response = MagicMock()
    mock_response.read.return_value = ics_data
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response
    
    # Mock existing events list
    mock_list_req = MagicMock()
    mock_list_req.execute.return_value = {"items": [{"id": "ev1", "description": "OTA Block\nota:existing-uid"}]}
    mock_calendar_client._service.events().list.return_value = mock_list_req
    
    mock_insert_req = MagicMock()
    mock_calendar_client._service.events().insert.return_value = mock_insert_req

    await sync_ota(mock_config, mock_calendar_client)
    
    mock_calendar_client._service.events().insert.assert_not_called()
