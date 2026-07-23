# modules/booking/calendar.py
import base64
import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import pytz
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_credentials() -> Credentials:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    service_account_info = json.loads(base64.b64decode(raw))
    return Credentials.from_service_account_info(service_account_info, scopes=SCOPES)


def _get_redis():
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        return None
    try:
        import redis
        r = redis.from_url(redis_url)
        r.ping()
        return r
    except Exception:
        return None

class CalendarClient:
    def __init__(self, calendar_id: str, calendar_owner_email: str,
                 timezone: str = "Europe/Rome"):
        self._calendar_id = calendar_id
        self._owner_email = calendar_owner_email
        self._tz = pytz.timezone(timezone)
        creds = _get_credentials()
        self._service = build("calendar", "v3", credentials=creds)

    def _range_key(self, checkin: date, checkout: date) -> str:
        return f"range_lock:{checkin.isoformat()}:{checkout.isoformat()}"

    def is_range_available(
        self,
        checkin: date,
        checkout: date,
        requester_phone: str | None = None,
        exclude_event_id: str | None = None,
    ) -> bool:
        """Check Google Calendar + Redis soft locks.

        A lock created by the same requester (e.g. their own still-pending
        approval request) never blocks that same requester — otherwise a
        guest confirming their own booking collides with the lock the bot
        itself created moments earlier for the very same request.

        exclude_event_id lets a modification flow check availability while
        ignoring the guest's own existing event for that stay.
        """
        r = _get_redis()
        if r:
            # Check if any lock overlaps with this range
            for key in r.keys("range_lock:*"):
                key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                _, lock_checkin_str, lock_checkout_str = key_str.split(":")
                lock_checkin = date.fromisoformat(lock_checkin_str)
                lock_checkout = date.fromisoformat(lock_checkout_str)
                # Overlap: max(start1, start2) < min(end1, end2)
                if max(checkin, lock_checkin) < min(checkout, lock_checkout):
                    if requester_phone:
                        lock_owner = r.get(key)
                        lock_owner_str = lock_owner.decode("utf-8") if isinstance(lock_owner, bytes) else lock_owner
                        if lock_owner_str == requester_phone:
                            continue  # it's our own pending request, not a real conflict
                    return False

        # Assuming checkin at 15:00, checkout at 10:00 as typical defaults if not provided.
        # Hardcoding for now, should ideally come from config, but keeping it minimal.
        start_time = time(15, 0)
        end_time = time(10, 0)

        start_dt = self._tz.localize(datetime.combine(checkin, start_time))
        end_dt = self._tz.localize(datetime.combine(checkout, end_time))

        if exclude_event_id:
            # freebusy() only returns busy time ranges, not event ids, so it
            # can't exclude a specific event. List events in range instead.
            result = self._service.events().list(
                calendarId=self._calendar_id,
                timeMin=start_dt.isoformat(),
                timeMax=end_dt.isoformat(),
                singleEvents=True,
            ).execute()
            for event in result.get("items", []):
                if event["id"] == exclude_event_id:
                    continue
                return False
            return True

        body = {
            "timeMin": start_dt.isoformat(),
            "timeMax": end_dt.isoformat(),
            "items": [{"id": self._calendar_id}],
        }
        result = self._service.freebusy().query(body=body).execute()
        busy = result["calendars"][self._calendar_id]["busy"]
        return len(busy) == 0

    def lock_range(self, checkin: date, checkout: date, requester_phone: str = "1") -> None:
        """Soft-lock a date range with no auto-expiry.

        Stores requester_phone as the value so is_range_available() can later
        recognize "this lock is mine" and not block the same requester.
        """
        r = _get_redis()
        if r:
            # No TTL, must be released explicitly
            r.set(self._range_key(checkin, checkout), requester_phone)

    def release_range(self, checkin: date, checkout: date) -> None:
        r = _get_redis()
        if r:
            r.delete(self._range_key(checkin, checkout))

    # Google Calendar color IDs
    COLOR_PENDING = "5"   # Banana (yellow) — waiting for owner approval
    COLOR_CONFIRMED = "10"  # Basil (green)  — owner approved

    def confirm_event(self, event_id: str) -> None:
        """Yellow → Green: owner approved the booking."""
        self._service.events().patch(
            calendarId=self._calendar_id,
            eventId=event_id,
            body={"colorId": self.COLOR_CONFIRMED},
        ).execute()

    def has_pending_lock(self, checkin: date, checkout: date, requester_phone: str) -> bool:
        """Check if this requester already has a pending lock for overlapping dates."""
        r = _get_redis()
        if not r:
            return False
        for key in r.keys("range_lock:*"):
            key_str = key.decode("utf-8") if isinstance(key, bytes) else key
            _, lc, lo = key_str.split(":")
            if max(checkin, date.fromisoformat(lc)) < min(checkout, date.fromisoformat(lo)):
                owner = r.get(key)
                if owner and (owner.decode("utf-8") if isinstance(owner, bytes) else owner) == requester_phone:
                    return True
        return False

    def create_event(
        self, checkin_date: date = None, checkout_date: date = None,
        guest_name: str = "", guest_phone: str = "", guests_count: int = 1,
        total_price: int = 0, language: str = "en", payment_state: str = "pending",
        request_id: str = "", color_id: str = "10", **kwargs
    ) -> str:
        # Fallback to old params for testing backward compat in main until fully refactored
        if 'slot' in kwargs:
            from dataclasses import dataclass
            
            @dataclass
            class _Slot:
                date: date
                start_time: time
                location: str

            slot = kwargs.pop('slot')
            checkin_date = slot.date
            checkout_date = slot.date + timedelta(days=1)
            # Recursively call standard interface
            return self.create_event(
                checkin_date=checkin_date, checkout_date=checkout_date,
                guest_name=kwargs.get('user_name', ''), guest_phone=kwargs.get('user_phone', ''),
                guests_count=1, total_price=kwargs.get('price', 0), language="en", payment_state="pending", request_id="compat"
            )
        start_time = time(15, 0)
        end_time = time(10, 0)

        start_dt = self._tz.localize(datetime.combine(checkin_date, start_time))
        end_dt = self._tz.localize(datetime.combine(checkout_date, end_time))

        description = (
            f"Phone: {guest_phone}\n"
            f"Guests: {guests_count}\n"
            f"Total: ${total_price:,}\n"
            f"Language: {language}\n"
            f"Payment: {payment_state}\n"
            f"Request ID: {request_id}"
        )

        event = {
            "summary": f"Stay - {guest_name}",
            "description": description,
            "colorId": color_id,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": str(self._tz)},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": str(self._tz)},
            "reminders": {"useDefault": False, "overrides": []},
        }

        result = self._service.events().insert(
            calendarId=self._calendar_id,
            body=event,
        ).execute()
        return result["id"]

    def find_upcoming_events_by_phone(self, phone: str) -> list[dict]:
        """Find future events that contain this phone number in the description."""
        now = datetime.now(self._tz).isoformat()
        result = self._service.events().list(
            calendarId=self._calendar_id,
            timeMin=now,
            maxResults=10,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        matching = []
        for event in result.get("items", []):
            desc = event.get("description", "")
            if phone in desc:
                start = event["start"].get("dateTime", "")
                # Format date as human-readable English
                date_str = start[:10] if start else ""
                if date_str:
                    from datetime import date as date_cls
                    d = date_cls.fromisoformat(date_str)
                    day_names = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
                                 4: "Friday", 5: "Saturday", 6: "Sunday"}
                    month_names = {1: "January", 2: "February", 3: "March", 4: "April",
                                   5: "May", 6: "June", 7: "July", 8: "August",
                                   9: "September", 10: "October", 11: "November", 12: "December"}
                    date_str = f"{day_names[d.weekday()]} {month_names[d.month]} {d.day}, {d.year}"
                matching.append({
                    "id": event["id"],
                    "summary": event.get("summary", ""),
                    "date": date_str,
                    "time": start[11:16] if start else "",
                    "location": event.get("location", ""),
                })
        return matching

    def delete_event(self, event_id: str) -> None:
        """Delete an event from the calendar."""
        self._service.events().delete(
            calendarId=self._calendar_id,
            eventId=event_id,
        ).execute()
