## What to build

A guest asks to cancel → the system lists upcoming Stays for their phone → the guest confirms which one → an approval(`cancel`) is sent to all approvers. On **approve** → the Google Calendar event is deleted/cancelled, with free-vs-full-liability policy messaging applied (free if the approval decision is ≥ `free_cancellation_days_before` full calendar days before check-in, Europe/Rome; otherwise full stay total liability). **No auto-charge in v1** — collection outside the free window is the Owner's offline responsibility. Guest + other approvers notified. On **reject** → the Stay remains unchanged.

## Acceptance criteria

- [ ] Guest sees their upcoming stays (by phone) and confirms which to cancel
- [ ] Cancel requires approver approve; the Google Calendar event is removed only on approve
- [ ] Policy messaging states free cancel (≥ free_cancellation_days_before) vs full liability; no auto Stripe charge
- [ ] Reject keeps the Stay; guest + other approvers notified

## Blocked by

- #5 — Guest booking flow end-to-end (create → approval → outcome)
