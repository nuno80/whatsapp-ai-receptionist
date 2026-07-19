## What to build

An OTA sync module that is a **no-op** when `ota.ical_urls` is empty or `modules.ota_sync` is off (no errors). Otherwise: fetch each ICS feed, parse VEVENT date ranges, and upsert **OTA block** events on the master Google Calendar keyed by `ota:{uid}` in the description (idempotent — re-runs update, don't duplicate). Those busy ranges block availability (freebusy). Triggered by an authenticated `POST /internal/sync-ota` (same `X-Internal-Secret` pattern as reminders) + external cron. **Read-only import — never write availability back to Booking/Airbnb.**

## Acceptance criteria

- [ ] Empty `ical_urls` or module off → no-op, no errors
- [ ] With URLs, VEVENT ranges upsert OTA block events keyed by `ota:{uid}` (idempotent re-runs)
- [ ] OTA blocks block availability (freebusy)
- [ ] Authenticated `POST /internal/sync-ota` trigger; read-only, never write-back to OTA

## Blocked by

- #1 — Foundation: B&B config schema + pricing & min-stay rules
- #2 — Calendar stay model (Google Calendar)
