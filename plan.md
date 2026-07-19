# Plan: WhatsApp AI Receptionist → B&B Roma (1 room)

**Mode:** ponytail full — shortest path that ships. Reuse existing patterns; no new frameworks; no multi-property / no auto-rules / no billing automation.

**Source of truth:** `contest.md` (current code), business requirements below. Original repo is already this tree (not a fresh fork).

---

## Goal

Turn hourly appointment bot (dentist/salon) into multi-night stay bot for **one double room**. Google Calendar = master availability. Human family approval required. Stripe for pay links. Deploy on VPS (Docker + Caddy).

---

## What we keep as-is

| Piece | Why |
|-------|-----|
| FastAPI + direct Anthropic SDK | Already correct (no LangChain) |
| Intent JSON in reply + regex extract | Works; only change field shapes |
| Redis dual backend (history, locks, pending_*) | Reuse for approval lock |
| YAML config + `${ENV}` loader | Extend sections, no DB |
| WhatsApp client, phone norm, Whisper | Untouched |
| `POST /internal/send-reminders` cron hook | Same trigger, new message content |

---

## What we cut (YAGNI)

| Spec item | Decision |
|-----------|----------|
| Approval timeout / nudge | **Skip** — backlog until family complains |
| Auto pricing / seasonal rules | **Never** in v1 — manual YAML only |
| Invoice automation | **Skip** |
| Next.js booking widget / live calendar | **Skip** — site is brochure only |
| Multi-room / multi-property | **Never** |
| Write-back to OTA | **Never** — iCal import only |
| Channel manager | **Never** — one Google Calendar |
| Prompt caching v1 | Optional one-liner later; not a blocker |
| Separate approval package tree if empty | Single module file is enough |

---

## Target flow (delta from today)

```
Guest WhatsApp
  → Claude (Giulia) + intent JSON (checkin/checkout/guests)
  → validate dates + min stay + price + freebusy
  → Redis pending request + WA to 4 approvers
  → first approver OK (SETNX lock)
  → calendar event (or cancel/modify) + guest confirm
  → optional Stripe Payment Link (deposit | full | none if on-site)
  → other 3: "gestita da X"
```

Today the bot creates the calendar event immediately on `booking_confirmed`. **That path must go through approval first.**

---

## Config shape (`config.yaml`)

Replace dentist services/locations/hours with B&B fields. Loader stays unchanged.

```yaml
client:
  name: "B&B …"
  timezone: "Europe/Rome"

modules:
  booking: true
  payments: true   # Stripe
  reminders: true
  ota_sync: false  # flip when iCal URLs exist

bot_persona:
  name: "Giulia"
  tone: "cordiale-professionale"
  declares_as_ai: true

authorized_approvers:
  - phone: "+39…"
    name: "…"
  # ×4

booking:
  calendar_id: "${GOOGLE_CALENDAR_ID}"
  calendar_owner_email: "${GOOGLE_CALENDAR_OWNER_EMAIL}"
  max_guests: 2
  checkin_time: "15:00"
  checkout_time: "10:00"
  cancellation_policy:
    free_cancellation_days_before: 7
  pricing_periods:
    - { start_date: "2026-01-01", end_date: "2026-12-31", price_per_night: 120 }
  minimum_stay_periods:
    - { start_date: "2026-01-01", end_date: "2026-12-31", min_nights: 2 }

payment_mode: deposit          # deposit | full_on_site | full_online
deposit_percentage: 30

payments:
  provider: stripe
  currency: eur

ota:
  ical_urls: []                # empty → ota_sync no-ops
  poll_minutes: 30

reminders:
  hours_before: 48
  # templates per lang or one IT default + AI-free format strings
```

**Overlap rule (fixed, no debate later):** for a given night, scan lists **last match wins**. Owner edits YAML carefully; we don't build an admin UI.

---

## Implementation order (PRs / commits)

Do in this order. Each step should leave tests green.

### 0. Housekeeping
- Delete/ignore `railway.toml` when Docker is ready (or leave dead until deploy).
- Env: drop `MP_*`; add `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`.
- Model id in `core/ai.py`: switch to `claude-sonnet-5` (or exact Anthropic model string available at implement time).

### 1. Config + pure pricing helpers
**Files:** `config.yaml`, small pure functions (can live in `modules/booking/pricing.py` or bottom of calendar module — prefer one file if short).

- `price_for_stay(checkin, checkout, periods) → total_cents` (sum per night, last-match period).
- `min_nights_ok(checkin, checkout, periods) → bool`.
- No services list, no locations list, no business_hours.

**Tests:** table-driven nights across period boundaries; min stay fail/pass.

### 2. Rewrite `modules/booking/calendar.py` (date ranges)
**Replace slot model with stay ranges.**

| Old | New |
|-----|-----|
| `Slot(date, start_time, location)` | `Stay(checkin: date, checkout: date)` |
| `is_slot_available(d, t, duration_min)` | `is_range_available(checkin, checkout)` freebusy over nights |
| `lock_slot` Redis key by hour | `lock_range` key by `checkin:checkout` (TTL while pending approval) |
| `create_event(service, …, slot, duration)` | `create_event(guest, phone, stay, total, guests, policy text)` with fixed checkin/checkout times on event start/end |
| business_hours | delete |

Keep: credentials, freebusy, find-by-phone in description, delete_event.

**Event description convention (stable for reminders/cancel):**
```
Guests: 2
Phone: 39…
Total: 360 EUR
Status: pending|confirmed
…
```

### 3. Approval flow (critical path)
**File:** `modules/approval/flow.py` (one module; not a framework).

Reuse Redis patterns already in `main.py` (`SET` nx, `setex`, pending_* keys).

```
approval:{id}     → JSON {type, payload, guest_phone, status, created_at}
approval:claim:{id} → SETNX on first OK  (atomic winner)
```

**API (functions, not classes-for-one):**
- `create_request(type, payload) → id`
- `notify_approvers(id, summary_text)` — fan-out WA
- `try_claim(id, approver_phone) → bool` — SETNX
- `mark_done(id, by_name)` + `notify_others`

**Wire in `main.py`:**
1. On guest `booking_confirmed` / cancel / modify intents: **do not** write calendar yet. Create approval request, message guest "in attesa di conferma", message all approvers with short id + summary.
2. Early in webhook: if `from` ∈ `authorized_approvers` and text matches approve/reject + id (or reply-to pending list), handle as approval path **before** AI chat. Simplest match: message contains request id or `OK <id>` / `NO <id>`. Fallback: if exactly one pending for that approver channel, bare `OK` works.
3. Winner: claim → run calendar action → guest WA → others "gestita da {name}".

**Skip timeout/nudge** (backlog). Pending TTL e.g. 48h Redis expire is enough.

**Tests:** two concurrent claims → one winner (mock Redis or fake lock).

### 4. `core/ai.py` + knowledge
- Persona from `bot_persona` (name, AI disclosure, tone).
- Intent JSON for stays:
  ```json
  {"intent":"booking_confirmed","checkin":"YYYY-MM-DD","checkout":"YYYY-MM-DD","guests":2,"user_name":"…"}
  ```
  Cancel/modify intents stay similar; drop service/location/time-of-day.
- Pre-calculated **free date ranges** (next N free windows from freebusy), inject into prompt — same anti-hallucination idea as current next-5-dates.
- Language: Claude already "respond in user's language". Constrain to IT/EN/ES/FR/DE in prompt. Knowledge load: `knowledge/{lang}.txt` with fallback `knowledge/it.txt`. Detect: cheap heuristic (Claude tag in JSON `"lang":"it"` is fine) — **no** extra translation API.
- Files: `knowledge/it.txt` … `de.txt` (owner content; start with stubs).

### 5. `core/main.py` intent handlers
- `_handle_booking_intent` → validate stay → price/min stay → **approval**, not create.
- Cancel/modify → approval with type + event id.
- Drop `_find_service` / `_find_location`.
- Approver branch at top of process_message.
- Payment: only after approval (or on approve): if `full_on_site` skip link; else Stripe link for deposit % or full.

### 6. Payments: Stripe, delete Mercado Pago
**Files:** replace `mercadopago.py` with `stripe_pay.py` (or `stripe_client.py`).

- Use **Payment Links** or Checkout Session create → URL in WA. Prefer Checkout Session if Payment Link API is clumsier for one-off amounts; either is fine if one function returns a URL.
- Webhook `POST /payments/webhook` with Stripe signature; map metadata `{phone, approval_id}` → update event description / notify guest.
- Remove `mercadopago` from `requirements.txt`; add `stripe`.
- Rewrite tests that hit MP.

### 7. Reminders
- Query events with check-in in `[now+hours_before window]` (not "all of tomorrow" only if hours_before varies — keep simple: check-in date = target day).
- Template includes check-in time + short arrival blurb; language from stored guest lang if present else IT.

### 8. OTA iCal import (stub-ready)
**File:** `modules/booking/ota_sync.py`

- If `ota.ical_urls` empty or `modules.ota_sync` false → no-op.
- Else: fetch ICS, parse VEVENT date ranges, upsert "OTA block" events on master calendar (idempotent key in description: `ota:{uid}`).
- Trigger: `POST /internal/sync-ota` (same auth as reminders) + external cron every 30 min. **No** in-process APScheduler unless already present (it isn't).

Dependency: only if stdlib parsing is painful — add `icalendar` (one lib). Prefer that over hand-rolled ICS.

### 9. Deploy
- `Dockerfile` (uvicorn), `docker-compose.yml` (app + redis).
- `Caddyfile` for HTTPS (domain TBD).
- Drop Railway as primary path.
- Ops checklist (not code): Meta WA Business app, domain DNS, Google SA, Stripe webhook endpoint, env secrets on VPS.

### 10. Website phase 1
- Separate folder `website/` or sibling repo — **minimal Next.js static pages**: photos, copy, map link, `wa.me` CTA.
- No API to this backend in phase 1.
- **Ponytail note:** if Next is overkill for a brochure, plain static HTML in `website/` is fine; use Next only if you already want the phase-2 path.

---

## File touch map

| Path | Action |
|------|--------|
| `config.yaml` | rewrite |
| `config/loader.py` | likely untouched |
| `modules/booking/calendar.py` | rewrite stay logic |
| `modules/booking/pricing.py` | new (optional if tiny → stay in calendar) |
| `modules/booking/ota_sync.py` | new |
| `modules/approval/flow.py` | new |
| `modules/payments/mercadopago.py` | delete |
| `modules/payments/stripe_pay.py` | new |
| `core/ai.py` | persona, intents, free ranges, knowledge path |
| `core/main.py` | approval gate + stay handlers + approver branch + Stripe webhook |
| `reminders/scheduler.py` | check-in window + template |
| `knowledge/*.txt` | 5 langs |
| `requirements.txt` | stripe, drop mercadopago; maybe icalendar |
| `tests/*` | rewrite booking/payment/main; add approval + pricing |
| `Dockerfile`, `docker-compose.yml`, `Caddyfile` | new |
| `railway.toml` | remove or leave unused |
| `website/` | phase 1 brochure |

---

## Acceptance criteria (v1 done when)

1. Guest can ask availability and request stay; bot never confirms without family OK.
2. First of 4 approvers with OK claims request; calendar event created once; others notified.
3. Price = sum of nightly rates across periods; min stay enforced.
4. Same-day check-in allowed if free and min stay ok.
5. Cancel free only if ≥ `free_cancellation_days_before` before check-in (message policy; enforce in cancel handler).
6. Payment mode from config drives link vs on-site.
7. Reminders fire pre-check-in.
8. iCal module idle with empty URLs; with URL, blocks appear on calendar.
9. Bot answers as Giulia in guest language; knowledge file matches language.
10. `docker compose up` runs app + redis; Caddy terminates TLS.

---

## Explicit backlog (do not build now)

- Approval timeout / reminder to family
- Embedded booking widget + live availability on site
- Italian e-invoicing
- Auto seasonal pricing
- Fully automatic confirm (no human)
- Write to OTA

---

## Suggested first coding session

1. Config rewrite + pricing pure functions + tests
2. Calendar range availability + create_event
3. Approval module + main.py gate

Then AI intents, Stripe, reminders, iCal, deploy, site.

---

## Ponytail summary

- **Reuse** Redis lock/pending patterns in `main.py`; same intent-JSON design.
- **One** approval module, not a workflow engine.
- **Manual** YAML for price/min stay/payment mode — no rule engine.
- **Cron HTTP** for reminders + iCal, not a second process framework.
- **Skip** timeout, invoices, live web calendar until needed.
