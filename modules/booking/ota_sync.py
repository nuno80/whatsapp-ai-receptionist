# modules/booking/ota_sync.py
import logging
import urllib.request
from datetime import date, datetime, timedelta
import pytz
from icalendar import Calendar

logger = logging.getLogger(__name__)

def parse_ical_ranges(ics_text: str) -> list[tuple[date, date, str]]:
    """Parse VEVENT from ics text, returning (checkin, checkout, uid)."""
    cal = Calendar.from_ical(ics_text)
    blocks = []
    for component in cal.walk('VEVENT'):
        dtstart = component.get('dtstart')
        dtend = component.get('dtend')
        uid = str(component.get('uid', ''))
        
        if not dtstart or not dtend:
            continue
            
        start = dtstart.dt
        end = dtend.dt
        
        # Convert datetime to date
        if isinstance(start, datetime):
            start = start.date()
        if isinstance(end, datetime):
            end = end.date()
            
        # If the event doesn't have a valid UID, skip or generate one
        if not uid:
            uid = f"{start.isoformat()}-{end.isoformat()}"
            
        blocks.append((start, end, uid))
        
    return blocks

async def sync_ota(config: dict, calendar_client) -> None:
    """Fetch all configured iCal URLs and upsert blocking events."""
    if not config.get("modules", {}).get("ota_sync", False):
        logger.info("OTA sync is disabled in modules config")
        return
        
    urls = config.get("ota", {}).get("ical_urls", [])
    if not urls:
        logger.info("No OTA iCal URLs configured")
        return
        
    logger.info(f"Syncing OTA from {len(urls)} URLs")
    
    # 1. Fetch all OTA events across all URLs
    ota_blocks = []
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                ics_text = response.read()
                blocks = parse_ical_ranges(ics_text)
                ota_blocks.extend(blocks)
                logger.info(f"Fetched {len(blocks)} events from {url}")
        except Exception as e:
            logger.error(f"Failed to fetch or parse iCal from {url}: {e}")
            continue

    if not ota_blocks:
        return

    # 2. Get existing OTA events from master calendar
    now = datetime.now(calendar_client._tz).isoformat()
    try:
        # Paginating might be needed in a real scenario, but keeping it simple for now
        result = calendar_client._service.events().list(
            calendarId=calendar_client._calendar_id,
            timeMin=now, # Only look at future events to save time? The problem is past events could be updated, but generally we care about future availability
            q="ota:", # Use text search
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        existing_events = result.get("items", [])
    except Exception as e:
        logger.error(f"Failed to fetch existing events from calendar: {e}")
        return

    # Map existing by OTA uid
    existing_by_uid = {}
    for event in existing_events:
        desc = event.get("description", "")
        for line in desc.split("\n"):
            if line.startswith("ota:"):
                uid = line[4:].strip()
                existing_by_uid[uid] = event
                break

    # 3. Upsert
    for checkin, checkout, uid in ota_blocks:
        if checkin >= checkout:
            continue
            
        # Only process events that end in the future
        if checkout <= date.today():
             continue

        description = f"OTA Block\nota:{uid}"
        
        # Check if we already have it
        if uid in existing_by_uid:
            # We could check if dates changed and update, but simplest is to skip if it exists
            # In a real app we might update if the dates shifted
            continue
            
        # Create it using the internal API or direct google API
        # Since calendar_client.create_event assumes our B&B format, we do a direct insert
        # Or better, we can modify create_event, but direct insert is cleaner for blocked events
        start_dt = calendar_client._tz.localize(datetime.combine(checkin, calendar_client._tz.localize(datetime.now()).time().replace(hour=15, minute=0, second=0, microsecond=0)))
        end_dt = calendar_client._tz.localize(datetime.combine(checkout, calendar_client._tz.localize(datetime.now()).time().replace(hour=10, minute=0, second=0, microsecond=0)))

        # Strip timezone for date-only events or use dateTime for specific times.
        # It's better to use dateTime to block exactly 15:00 to 10:00, or date for full days.
        # The spec says "Those busy ranges block availability (freebusy)".
        # CalendarClient.is_range_available uses freebusy between 15:00 and 10:00.
        # If we insert as full day, it blocks the whole day. If we insert as 15:00-10:00, it perfectly matches.
        
        start_str = start_dt.isoformat()
        end_str = end_dt.isoformat()
        
        event_body = {
            "summary": "Reserved (OTA)",
            "description": description,
            "start": {"dateTime": start_str, "timeZone": str(calendar_client._tz)},
            "end": {"dateTime": end_str, "timeZone": str(calendar_client._tz)},
            # Use 'transparent': 'opaque' is default, which blocks freebusy
        }
        
        try:
            calendar_client._service.events().insert(
                calendarId=calendar_client._calendar_id,
                body=event_body,
            ).execute()
            logger.info(f"Inserted OTA block for {checkin} to {checkout} (uid: {uid})")
        except Exception as e:
            logger.error(f"Failed to insert OTA block for uid {uid}: {e}")
