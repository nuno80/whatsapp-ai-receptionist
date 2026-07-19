## What to build

A loadable B&B `config.yaml` that replaces the dentist starter-kit schema (services / locations / business_hours) with the v1 surface: client name + `Europe/Rome` timezone, `bot_persona`, four `authorized_approvers` (phone + display name), `max_guests: 2`, check-in/check-out times, cancellation `free_cancellation_days_before`, `pricing_periods`, `minimum_stay_periods`, `payment_mode` + `deposit_percentage`, `ota`, `reminders`. The existing YAML loader (`config/loader.py`, `${ENV_VAR}` substitution) stays unchanged.

Plus pure, table-tested domain rules:
- **Stay total** = sum of the nightly price for each night of the stay (`checkin` inclusive … `checkout` exclusive). For a given night, among all pricing periods whose inclusive `start_date`/`end_date` cover that night, **the last matching entry in the config list wins**. A stay may cross multiple periods.
- **Minimum stay** = the **maximum** of `min_nights` among all minimum-stay periods that cover **any** night of the stay. Request nights must be ≥ that value.
- **Missing price** → the request is **invalid** (no silent default price). The Owner must cover the calendar with pricing + min-stay periods.

This is the dependency root for nearly every other ticket.

## Acceptance criteria

- [ ] `config.yaml` loads with the B&B schema and no dentist fields; loader unchanged
- [ ] Stay total = sum of nightly prices; per-night last-list-match; inclusive period dates
- [ ] Min stay = max of `min_nights` across periods touching any night of the stay
- [ ] A request with any night not covered by a pricing period is rejected (no implicit default)
- [ ] Table-driven tests cover period boundaries, multi-period stays, min-stay pass/fail, and uncovered-night rejection

## Blocked by

- None — can start immediately.
