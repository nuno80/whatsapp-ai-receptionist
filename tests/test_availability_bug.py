"""
Reproduce: free_ranges says 26/07-23/10 is free, 
but is_range_available returns False for 08/08-11/08.
"""
import pytest
from datetime import date
from unittest.mock import MagicMock, patch
import pytz

from modules.booking.calendar import CalendarClient


@pytest.fixture
def cal():
    """Real CalendarClient with mocked Google API service."""
    with patch("modules.booking.calendar._get_credentials"):
        with patch("modules.booking.calendar.build") as mock_build:
            service = MagicMock()
            mock_build.return_value = service
            client = CalendarClient(
                calendar_id="test@calendar",
                calendar_owner_email="owner@test.com",
                timezone="Europe/Rome",
            )
            # Default: calendar is empty (no busy periods)
            service.freebusy().query().execute.return_value = {
                "calendars": {"test@calendar": {"busy": []}}
            }
            return client


def test_no_redis_no_events_should_be_available(cal):
    """With no Redis and no calendar events, Aug 8-11 must be available."""
    with patch("modules.booking.calendar._get_redis", return_value=None):
        result = cal.is_range_available(
            date(2026, 8, 8), date(2026, 8, 11), requester_phone="391234567890"
        )
    assert result is True, "Empty calendar + no Redis should be available"


def test_unrelated_redis_lock_should_not_block(cal):
    """A Redis lock for July 25-27 must NOT block August 8-11."""
    mock_redis = MagicMock()
    mock_redis.keys.return_value = [b"range_lock:2026-07-25:2026-07-27"]
    mock_redis.get.return_value = b"399999999999"

    with patch("modules.booking.calendar._get_redis", return_value=mock_redis):
        result = cal.is_range_available(
            date(2026, 8, 8), date(2026, 8, 11), requester_phone="391234567890"
        )
    assert result is True, "Non-overlapping lock should not block"


def test_overlapping_lock_different_owner_blocks(cal):
    """A Redis lock for Aug 5-10 by a different phone SHOULD block Aug 8-11."""
    mock_redis = MagicMock()
    mock_redis.keys.return_value = [b"range_lock:2026-08-05:2026-08-10"]
    mock_redis.get.return_value = b"399999999999"

    with patch("modules.booking.calendar._get_redis", return_value=mock_redis):
        result = cal.is_range_available(
            date(2026, 8, 8), date(2026, 8, 11), requester_phone="391234567890"
        )
    assert result is False, "Overlapping lock from different owner should block"


def test_overlapping_lock_same_owner_allows(cal):
    """A Redis lock for Aug 8-11 by the SAME phone should NOT block."""
    mock_redis = MagicMock()
    mock_redis.keys.return_value = [b"range_lock:2026-08-08:2026-08-11"]
    mock_redis.get.return_value = b"391234567890"

    with patch("modules.booking.calendar._get_redis", return_value=mock_redis):
        result = cal.is_range_available(
            date(2026, 8, 8), date(2026, 8, 11), requester_phone="391234567890"
        )
    assert result is True, "Own lock should not block self"


def test_freebusy_busy_blocks_even_without_redis(cal):
    """If freebusy says Aug 8-11 is busy (real event on calendar), should block."""
    cal._service.freebusy().query().execute.return_value = {
        "calendars": {"test@calendar": {"busy": [
            {"start": "2026-08-09T15:00:00+02:00", "end": "2026-08-10T10:00:00+02:00"}
        ]}}
    }

    with patch("modules.booking.calendar._get_redis", return_value=None):
        result = cal.is_range_available(
            date(2026, 8, 8), date(2026, 8, 11), requester_phone="391234567890"
        )
    assert result is False, "Busy period on calendar should block"
