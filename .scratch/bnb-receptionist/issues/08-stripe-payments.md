## What to build

Mercado Pago is replaced by **Stripe**. A payment link (Payment Link or Checkout Session) is sent **right after an approver approve**, driven by payment mode: `full_on_site` → no link (balance due on site); `full_online` → 100% of the Stay total; `deposit` → `deposit_percentage` of the total (remainder on site). Occupancy is held on the calendar at approve, so dates are blocked regardless of payment; unpaid stays remain on calendar (v1: **no auto-release on non-payment**).

A Stripe webhook with signature validation marks the Stay's paid state and sends the guest a short payment-received confirmation; invalid signatures are rejected. EUR only. **No bot-initiated Stripe refunds** (Owner refunds manually in the Dashboard). `requirements.txt` and `.env.example` updated; Mercado Pago code and tests removed.

## Acceptance criteria

- [ ] Payment mode drives link vs on-site; the link is sent only after approver approve
- [ ] Stripe webhook validates signatures; updates the paid state on the Stay; notifies the guest
- [ ] Unpaid stays remain on calendar; no auto-release on non-payment
- [ ] EUR only; no bot-initiated refunds; Mercado Pago module/tests/requirements removed; `stripe` added

## Blocked by

- #1 — Foundation: B&B config schema + pricing & min-stay rules
- #5 — Guest booking flow end-to-end (create → approval → outcome)
