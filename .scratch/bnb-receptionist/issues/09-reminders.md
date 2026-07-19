## What to build

The reminder job fires for confirmed Stays whose check-in falls within `hours_before` (default 48) and sends a WhatsApp message to the guest's phone in the guest's stored language (fallback IT) with the check-in time and a short arrival / how-to-get-there blurb (from template / knowledge). **Pure OTA blocks get no reminder.** The authenticated internal HTTP trigger (`POST /internal/send-reminders`, `X-Internal-Secret`) stays the same; it is driven by external cron.

## Acceptance criteria

- [ ] Reminders fire only for confirmed Stays with check-in within `hours_before`
- [ ] Message is in the guest's stored language (fallback IT) with check-in time + arrival blurb
- [ ] Pure OTA blocks (no guest phone / OTA-tagged) get no reminder
- [ ] Authenticated `POST /internal/send-reminders` trigger unchanged

## Blocked by

- #2 — Calendar stay model (Google Calendar)
- #3 — Giulia persona + stay intent schema + free ranges + 5-language knowledge
