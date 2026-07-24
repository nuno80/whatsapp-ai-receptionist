import os
import json
from dotenv import load_dotenv
from modules.booking.calendar import CalendarClient

load_dotenv()

def main():
    cal_id = os.getenv("GOOGLE_CALENDAR_ID")
    if not cal_id:
        print("No GOOGLE_CALENDAR_ID in .env")
        return

    try:
        cal_owner = os.getenv("GOOGLE_CALENDAR_OWNER_EMAIL", "")
        client = CalendarClient(calendar_id=cal_id, calendar_owner_email=cal_owner)
        events = client._service.events().list(
            calendarId=cal_id,
            timeMin="2024-01-01T00:00:00Z",
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        items = events.get("items", [])
        if not items:
            print("Calendar is empty.")
        else:
            print(f"Found {len(items)} events:")
            for e in items:
                start = e.get("start", {}).get("dateTime", e.get("start", {}).get("date"))
                end = e.get("end", {}).get("dateTime", e.get("end", {}).get("date"))
                summary = e.get("summary", "(No title)")
                color = e.get("colorId", "default")
                print(f"- {start} to {end} | {summary} | color: {color}")
    except Exception as e:
        print(f"Error fetching calendar: {e}")

if __name__ == "__main__":
    main()
