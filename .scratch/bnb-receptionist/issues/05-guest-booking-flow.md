## What to build

The first full vertical slice. A guest completes a create request; the system validates (checkin not before today under Europe/Rome, same-day allowed if free, checkout after checkin, max 2 guests, min stay, every night priced, freebusy free, no soft-lock overlap), creates an approval(`create`) + soft lock, and tells the guest "awaiting family confirmation" — **never** "confirmed" / "prenotato" / "booked". Approvers are notified (fan-out from the approval ticket).

On **approve** → a Google Calendar Stay event is created, the soft lock is released, and the guest + other approvers are notified. On **reject** → the soft lock is released and the guest is politely informed; no calendar change.

The old direct-create-calendar-event-on-`booking_confirmed`-intent path is removed. Guest phone normalization is fixed for Italy/Rome.

## Acceptance criteria

- [ ] Guest never sees "confirmed / prenotato / booked" before approver approve; sees "awaiting confirmation"
- [ ] All SPEC create validations enforced; failures return a reason to the guest with no approval created
- [ ] Approve creates exactly one Google Calendar stay event and releases the soft lock; guest + losing approvers notified
- [ ] Reject releases the soft lock and informs the guest; no calendar change
- [ ] Direct calendar creation on booking intent removed; guest phone normalized for Italy

## Blocked by

- #2 — Calendar stay model (Google Calendar)
- #3 — Giulia persona + stay intent schema + free ranges + 5-language knowledge
- #4 — Approval workflow on the single WhatsApp number
