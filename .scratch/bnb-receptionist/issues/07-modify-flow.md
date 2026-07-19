## What to build

A guest asks to modify → the Stay is identified → new checkin/checkout/guests collected → validated as a create (excluding the existing Stay event from busy) → an approval(`modify`) with old + new summary goes to all approvers. On **approve** → re-check freebusy excluding the old event, then swap (delete old event + create new) atomically from the product view, and **fully recompute the Stay total** from the current `pricing_periods` for the new nights (not the original total); show the new total to approver and guest. On **reject** → the old Stay is unchanged (the old event is not deleted before approve).

## Acceptance criteria

- [ ] Modify requires approver approve; the old event is not deleted before approve
- [ ] On approve, freebusy is re-checked excluding the old event; the swap is atomic from the product view
- [ ] Stay total is fully recalculated from current pricing periods for the new nights; the new total is shown to approver and guest
- [ ] Reject leaves the original Stay unchanged

## Blocked by

- #5 — Guest booking flow end-to-end (create → approval → outcome)
