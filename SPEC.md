# SPEC — B&B Roma WhatsApp Receptionist (v1)

**Status:** approved for implementation (grill complete)  
**Sources grilled:** `piano-modifiche-whatsapp-bnb.md`, `plan.md`, `contest.md` (as-is codebase)  
**Out of scope here:** line-by-line code design (see `plan.md` for build order)

This document defines **what the system must do** and **what it must not do**. Implementation choices that do not change guest/family-visible behaviour are left free unless they lock a product decision.

---

## 1. Product one-liner

A single-room B&B in Rome uses WhatsApp as the only booking channel. Guests chat with a virtual receptionist (**Giulia**). Family members **manually approve** every create / cancel / modify. **Google Calendar** is the single source of truth for occupancy. Online payments (when enabled by config) go through **Stripe**.

---

## 2. Actors

| Actor | Definition |
|-------|------------|
| **Guest** | Person messaging the B&B WhatsApp number about a stay (not in the approver list). |
| **Approver** | One of a fixed set of family members (exactly **4** phones in config) authorised to approve or reject pending requests. |
| **Owner** | Human who edits YAML config, knowledge files, prices, and Google Calendar; not a system role. |
| **Giulia** | Named AI receptionist persona; always presents as a **virtual assistant**, not a human host. |
| **Room** | The only bookable unit: **one double room**, max **2** guests. Price does **not** depend on guest count. |

_Avoid:_ “client” for Guest (starter kit used it for the business); “appointment”; “slot” for stays; “channel manager”.

---

## 3. Core domain objects

### 3.1 Stay request (guest-facing)

A Guest’s proposed occupation of the Room for consecutive nights:

| Field | Rules |
|-------|--------|
| `checkin` | Local calendar date (`Europe/Rome`). Same-day allowed. Not before today. |
| `checkout` | Date **after** checkin. Nights = `checkout − checkin` (checkout night is not occupied). |
| `guests` | Integer 1–2. |
| `guest_name` | Required before a request can enter approval. |
| `guest_phone` | WhatsApp sender id (normalised). |
| `language` | One of `it`, `en`, `es`, `fr`, `de`. |

### 3.2 Stay (booked occupancy)

A Stay exists only after an Approver has **approved** a create-request and the system has written the corresponding Calendar event (see §6 lifecycle).

Identified for cancel/modify by Calendar event id + guest phone match in event description.

### 3.3 Money

| Concept | Rules |
|---------|--------|
| **Night price** | EUR amount for one night, from Owner-managed **pricing periods**. |
| **Stay total** | Sum of night prices for each night of the stay (`checkin` inclusive … `checkout` exclusive). A stay may cross multiple periods. |
| **Deposit** | Percentage of Stay total when payment mode is `deposit`. |
| **Currency** | EUR only in v1. |

**Period overlap rule (fixed):** for a given night, among all periods whose range covers that night, **the last matching entry in the config list wins**. Inclusive `start_date` / inclusive `end_date` for period membership.

**Minimum stay rule (fixed):** required nights for a request = the **maximum** of `min_nights` among periods that cover **any** night of the stay. Request nights must be ≥ that value. If no period covers a night of the stay → request is **invalid** (Owner must cover calendar with pricing + min-stay periods; no silent default price).

### 3.4 Cancellation policy

Single global config: `free_cancellation_days_before: N`.

- **Free cancel window:** if cancel is approved and the approval decision time is at least **N full calendar days before check-in date** (timezone Rome), Guest owes nothing under policy messaging.
- **Outside window:** policy message states Guest is liable for the **full stay total**.  
  **v1 does not auto-charge residual via Stripe.** Collection outside free window is Owner’s offline responsibility unless payment already captured (see §7).

### 3.5 Payment mode (Owner-set, not date-based)

Exactly one active mode at a time in config:

| Mode | Behaviour after Stay is approved |
|------|----------------------------------|
| `full_on_site` | No payment link. Guest is told balance is due on site. |
| `full_online` | Stripe Checkout/Payment Link for **100%** of Stay total. |
| `deposit` | Stripe link for `deposit_percentage` of Stay total; remainder on site. |

Mode changes apply only to **new** Stay approvals after config reload/restart (same as other YAML).

### 3.6 Approval request

| Field | Meaning |
|-------|---------|
| `id` | Short unique id (guest/approver messages reference it). |
| `type` | `create` \| `cancel` \| `modify` |
| `status` | `pending` \| `approved` \| `rejected` |
| `payload` | Type-specific data (dates, guests, event id, totals, …) |
| `guest_phone` | Who to notify on outcome |
| `created_at` | For TTL |
| `resolved_by` | Approver display name when closed |

Only **one** Approver may claim a pending request (atomic lock). First successful claim wins; others get “gestita da {name}”.

### 3.7 Calendar event kinds

Master Google Calendar holds:

| Kind | Purpose |
|------|---------|
| **Stay event** | Occupancy from Guest booking (check-in time → check-out time from config). |
| **OTA block** | Imported busy range from external iCal (Booking/Airbnb). Not a Guest Stay. |

Any busy interval (Stay or OTA or manual Owner block) makes those nights **unavailable**.

### 3.8 Soft range lock

While an Approval request of type `create` or `modify` is `pending`, the system holds a **soft lock** on the requested date range so a second Guest cannot enter approval for overlapping nights. **No auto-expiry in v1:** the request and soft lock remain until an Approver approves or rejects (or an Owner clears state operationally). Status `expired` is reserved for backlog, not used by the runtime.

---

## 4. Invariants (must always hold)

1. **One Room** — no multi-unit, multi-property, or concurrent double occupancy.  
2. **No autonomous confirm** — the bot never tells a Guest a Stay is confirmed without a prior Approver **approve** on the matching Approval request.  
3. **Calendar is truth** — availability is freebusy on the master calendar + soft locks; the bot never invents free dates not derived from that.  
4. **Max 2 guests**; price independent of 1 vs 2.  
5. **Same-day check-in** allowed if free, min-stay ok, and not past under Rome timezone.  
6. **Approval fan-out** — every new pending Approval request notifies **all** Approvers.  
7. **Single winner** — concurrent Approver replies cannot produce two calendar side-effects.  
8. **OTA is inbound only** — never write availability back to Booking/Airbnb.  
9. **No e-invoicing** in v1.  
10. **No automatic seasonal pricing** — only Owner YAML periods.  
11. **Approver traffic is not Guest chat** — messages from Approver phones are handled by the approval path first; they must not drive booking intents for personal stays on the family numbers without explicit design (v1: Approver numbers are never Guests).

---

## 5. Conversational product (Giulia)

### 5.1 Persona

- Name from config (default **Giulia**).  
- Tone: cordiale-professionale (not slangy).  
- Explicitly states she is a **virtual assistant** of the B&B (at least once early in a conversation / when asked if human).  
- WhatsApp formatting only (single `*` bold, no markdown headings). Concise.

### 5.2 Languages

- Supported: **IT, EN, ES, FR, DE**.  
- Detect Guest language from conversation; reply in that language.  
- Knowledge: load Owner-authored `knowledge/{lang}.txt`; fallback `it` if missing.  
- **No machine translation** of knowledge content.

### 5.3 What Guests can do via chat

| Intent | Guest outcome before approval |
|--------|-------------------------------|
| Ask FAQ / directions / house rules | Answer from knowledge only; no side effects. |
| Ask availability | Propose only **pre-calculated free ranges** injected by the system. |
| Request booking | After checkin, checkout, guests, name collected → system validates → creates Approval `create` → Guest told request is **awaiting family confirmation** (not confirmed). |
| Request cancel | System finds Stay(s) by phone → Guest confirms which → Approval `cancel`. |
| Request modify | System finds Stay → Guest provides new dates → validate → Approval `modify`. |
| Voice notes | Transcribed then same as text. |

### 5.4 Intent payload (logical)

Create:

```text
intent: booking_requested   # naming may map to booking_confirmed in extractor; meaning is "ready for approval", not "confirmed stay"
checkin, checkout, guests, user_name, lang
```

Cancel:

```text
intent: cancellation_request | cancellation_confirmed + event_index
```

Modify:

```text
intent: modification_request | modification_confirmed + event_index
# then new dates via a create-shaped payload tied to the old event
```

**Critical product rule:** any language the Guest sees that says “confirmed / prenotato / booked” is allowed **only after** Approver approve (+ payment rules in §7). Before that: “richiesta inviata / awaiting confirmation”.

---

## 6. Lifecycle — create Stay

```
Guest conversation complete
    → Validate: dates, max guests, min stay, every night has price, freebusy free, no soft-lock overlap
    → Fail → Guest message with reason (no Approval)
    → Pass → Create Approval(create, pending) + soft-lock range
    → Notify all Approvers (summary: dates, guests, name, phone, total, request id)
    → Notify Guest: awaiting confirmation
    → Approver APPROVE (first claim wins)
         → Create Calendar Stay event (status confirmed or awaiting_payment per §7)
         → Release soft-lock (event now holds the busy)
         → Notify Guest of outcome
         → Notify other Approvers: managed by {name}
         → If payment mode needs online money → send Stripe link (§7)
    → Approver REJECT
         → Release soft-lock
         → Notify Guest politely that request cannot be accepted
         → Notify other Approvers: managed by {name}
    → (No auto-expiry / no Approver nudge in v1 — request stays `pending` until approve or reject)
```

### 6.1 Calendar Stay event shape (product)

- **Start:** checkin date + config `checkin_time` (Rome).  
- **End:** checkout date + config `checkout_time`.  
- **Summary:** guest name (and optional “B&B stay”).  
- **Description must include at least:** phone, guests, stay total, language, payment state, request id.  
  (Exact key strings are implementation detail; must be stable enough for find-by-phone and reminders.)

### 6.2 Cancel lifecycle

```
Guest asks cancel → list upcoming Stays for phone → Guest picks
    → Approval(cancel) to all Approvers
    → APPROVE → delete/cancel Calendar event → Guest + other Approvers notified
       Policy text applied (free vs full liability) in messages; no auto-charge in v1
    → REJECT → Guest told cancel not accepted; Stay remains
```

### 6.3 Modify lifecycle

```
Guest asks modify → identify Stay → new checkin/checkout/guests
    → Validate new range as create (excluding the existing Stay event from busy, or delete-then-create only after approve)
    → Approval(modify) with old + new summary
    → APPROVE → replace occupancy (delete old event, create new) atomically from product view
    → REJECT → old Stay unchanged
```

**Recommended atomicity:** do not delete the old event until Approver approves the new range; on approve, re-check freebusy (excluding old event), then swap. If re-check fails, Approver and Guest get failure message; old Stay remains.

**Modify pricing:** on approve, **Stay total is fully recalculated** from current `pricing_periods` for the new nights (not the original total). Approver summary and Guest messages must show the new total.

---

## 7. Payment (Stripe)

### 7.1 When money moves

| Mode | When link is sent | When Stay is “solid” for Guest messaging |
|------|-------------------|------------------------------------------|
| `full_on_site` | Never | Immediately after Approver approve |
| `deposit` / `full_online` | Immediately after Approver approve | Guest may be told “confirmed, complete payment” ; occupancy is **held on calendar at approve** so dates are blocked. Unpaid stays remain on calendar until Owner/Approver cancels (v1: **no auto-release on non-payment**). |

**Rationale (fixed for v1):** approval gates trust; calendar block gates inventory; payment is collection, not inventory lock. Avoids race where unpaid Checkout holds inventory offline while soft-lock expires. Owner can cancel unpaid Stays manually.

### 7.2 Webhook

- Stripe webhook marks payment state on the Stay (description / internal pending record).  
- Guest gets a short confirmation that payment was received.  
- Invalid signatures rejected.

### 7.3 Explicit non-goals

- No Italian e-invoicing.  
- **No bot-initiated Stripe refunds** (including free-cancellation window). Owner refunds manually in Stripe Dashboard when needed. Guest messaging may state that a refund will be handled by the host.  
- No multi-currency.

---

## 8. Approver UX

### 8.1 Notification content (minimum)

- Type (prenotazione / cancellazione / modifica)  
- Dates (and old→new if modify)  
- Guest name, phone, guests, total EUR  
- Request id  
- How to reply:
  - Prefer `OK <id>` / `NO <id>`.
  - Bare `OK` / `NO` is allowed **only when exactly one** Approval request is `pending` system-wide; otherwise the bot asks the Approver to include the id.

### 8.2 Claims

- First valid approve or reject that wins the atomic claim executes side effects.  
- Later replies: “already handled by {name}”.  
- Non-approver cannot claim.  
- Ambiguous bare `OK`/`NO` (zero or multiple pending): no claim; bot replies with the pending list / ids.

### 8.3 v1 non-goals

- No dashboard.  
- No timeout nudges to Approvers.  
- No auto-expiry of pending Approval requests (stays pending until approve/reject).  
- No partial approve (e.g. change price mid-flight) — reject and re-request instead.

---

## 9. Availability & OTA

### 9.1 Free ranges for the AI

System computes free consecutive night ranges from calendar freebusy (+ soft locks) and injects a limited set into the prompt. Giulia may only offer dates inside that set (or ask Guest for dates then validate server-side — both allowed; **server validation always wins**).

### 9.2 OTA sync

- Config list of iCal URLs; empty list or module off → no-op, no errors.  
- Periodic job (external cron → internal HTTP, same pattern as reminders).  
- Upsert OTA block events keyed by OTA event UID.  
- Read-only import.  
- License/ToS of OTA feeds verified when accounts go live (ops checklist, not code).

---

## 10. Reminders

- For each confirmed Stay with check-in at the configured horizon (`hours_before`, default **48**), send WhatsApp to guest phone from event description.  
- Content: check-in time, short arrival/how-to-get-there (from template / knowledge), Guest language if stored else IT.  
- Trigger: authenticated internal HTTP + external cron (existing pattern).  
- No reminder for pure OTA blocks.

---

## 11. Configuration surface (product)

Owner-editable without code changes:

- Client name, timezone (`Europe/Rome`)  
- Module toggles: booking, payments, reminders, ota_sync  
- Bot persona  
- Approver list (phone + display name)  
- Check-in / check-out times  
- Pricing periods, minimum-stay periods  
- Cancellation free-days  
- Payment mode + deposit %  
- OTA iCal URLs  
- Reminder hours_before + templates  
- Knowledge files × 5 languages  

Secrets stay in env (WhatsApp, Anthropic, Google SA, Stripe, Redis, internal secret).

---

## 12. Website

**Out of v1.** No public brochure/site is required for the first shipping cut. Guests reach the bot via WhatsApp only (number shared by Owner offline or later on a site).

Phase 1 brochure (photos, copy, `wa.me`) and phase 2 booking widget remain **backlog**.

---

## 13. Infrastructure (product constraints)

- Host: **VPS** + Docker Compose (app + Redis).  
- HTTPS reverse proxy: **Caddy** (preferred).  
- Public domain required for Meta webhook + Stripe webhook (not for a site in v1).  
- WhatsApp Business number dedicated, configured from zero.  
- Railway not the target path.

---

## 14. AI / model constraints

- Provider: Anthropic direct API (no LangChain).  
- Model: Claude Sonnet 5 class (`claude-sonnet-5` or the exact shipping model id).  
- Intent still embedded in natural reply (starter-kit pattern); server validates all side-effect data.  
- Prompt caching: optional optimisation, not required for correctness.

---

## 15. Acceptance criteria (v1)

1. Guest can complete a create request; until Approver OK, messaging never claims a firm booking.  
2. All four Approvers receive create/cancel/modify requests; first claim wins; others get managed-by notice.  
3. Overlapping create requests cannot both become Stay events.  
4. Stay total equals sum of nightly prices across periods (last-match).  
5. Min stay enforced with max-of-touched-periods rule.  
6. Same-day check-in works when free.  
7. Reject releases soft lock; Guest is informed.  
8. Payment mode drives link vs on-site; Stripe webhook updates paid state.  
9. Cancel/modify require approval and update calendar only on approve.  
10. Reminders fire pre-check-in with practical info.  
11. OTA module idle without URLs; with URLs, blocks appear and block availability.  
12. Giulia answers in Guest language with matching knowledge file.  
13. `docker compose up` + Caddy can expose HTTPS webhooks.  
14. No website is required for v1 acceptance.

---

## 16. Explicit backlog (not v1)

- Approver timeout nudges  
- Auto-expiry of pending Approval requests / soft locks  
- Auto-release unpaid Stays  
- Auto-charge / refund on late cancel  
- Public website brochure (phase 1) + embedded booking / live calendar (phase 2)  
- E-invoicing  
- Auto seasonal rules  
- Fully automatic confirm without Approvers  
- Multi-room / multi-property  
- OTA write-back  
- Bot-initiated Stripe refunds

---

## 17. Decisions resolved

These close gaps between `piano-modifiche-…`, `plan.md`, and grilling:

| Topic | Decision |
|-------|----------|
| Pricing overlap | Last list match wins; period dates inclusive. |
| Min stay across periods | Max of `min_nights` among periods touching the stay. |
| Missing price for a night | Reject request (no implicit default). |
| Confirm vs pay | Approver approve creates calendar occupancy; payment is separate collection. |
| Unpaid online stays | Stay stays on calendar; no auto-expiry of event in v1. |
| Pending Approval TTL | **Never auto-expire** — stays `pending` until Approver approve or reject. Soft lock held for the same duration. |
| Approver nudge | Out of v1. |
| Reject | First-class; releases lock; notifies Guest. |
| Approver phones | Never treated as Guests in v1. |
| Cancel fee enforcement | Policy messaging only; no auto Stripe capture of penalty. |
| Free ranges | Server-side validation always authoritative. |
| Modify pricing | Stay total **fully recalculated** from current `pricing_periods` for new nights. |
| Stripe refunds | **No bot refund API** — Owner refunds manually in Dashboard. |
| Approver reply | Bare `OK`/`NO` only if exactly one pending system-wide; else require id. |
| Website | **Out of v1** — no public site required; brochure + widget are backlog. |

---

## 18. Open questions

**None.** All grill questions resolved. This SPEC is ready to treat as **approved for implementation** unless you reopen a decision.

---

## 19. Glossary (ubiquitous language)

**Guest** — WhatsApp correspondent requesting information or a Stay; not an Approver.

**Approver** — Family member authorised to approve/reject Approval requests.

**Giulia** — Virtual receptionist persona of the bot.

**Room** — The single double room; only bookable resource.

**Stay** — Occupancy of the Room from check-in date/time to check-out date/time, represented by a Calendar Stay event after approval.

**Stay request** — Guest-proposed Stay not yet approved.

**Approval request** — Family-facing unit of work (`create` / `cancel` / `modify`) with atomic claim.

**Night** — One calendar night of occupation; priced independently; count = checkout − checkin days.

**Pricing period** — Owner-defined inclusive date range with a night price.

**Minimum-stay period** — Owner-defined inclusive date range with a minimum night count.

**Soft lock** — Temporary hold on a date range while an Approval request is pending.

**OTA block** — Busy range imported from an external iCal feed.

**Stay total** — Sum of night prices for all nights of a Stay.

**Payment mode** — Owner-selected `deposit` | `full_online` | `full_on_site`.

**Master calendar** — The single Google Calendar used as inventory truth.

_Avoid:_ appointment, slot (for multi-night), client (for Guest), channel manager, auto-confirm.
