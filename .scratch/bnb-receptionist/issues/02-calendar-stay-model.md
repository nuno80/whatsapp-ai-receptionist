## What to build

Google Calendar remains the single master inventory — the existing service-account auth and freebusy mechanism stay; only the booking model changes from hourly slots to night ranges. Replace the slot model with stay ranges:

- `is_range_available(checkin, checkout)` → freebusy over consecutive nights; free only when every night is free AND no soft lock overlaps.
- `create_event` writes a Google Calendar Stay event from `checkin_date + checkin_time` to `checkout_date + checkout_time`, with a description carrying at least phone, guests, stay total, language, payment state, and request id (stable enough for find-by-phone and reminders).
- `find_upcoming_events_by_phone` (kept) and `delete_event` (kept).
- A **date-range soft lock** with **no auto-expiry** — held for the approval lifecycle, released explicitly on approval outcome.

Old slot / business-hours logic and code removed.

## Acceptance criteria

- [ ] `is_range_available(checkin, checkout)` is free only when every night is free on Google Calendar (freebusy) and no soft lock overlaps
- [ ] `create_event` writes a Google Calendar event spanning checkin_date+checkin_time → checkout_date+checkout_time, with description including phone, guests, total, language, payment state, request id
- [ ] `find_upcoming_events_by_phone` finds stay events by phone in the description; `delete_event` works
- [ ] Range soft lock has no auto-expiry; explicitly released on approval outcome
- [ ] Slot / business-hours model and code removed; tests rewritten for ranges

## Blocked by

- #1 — Foundation: B&B config schema + pricing & min-stay rules
