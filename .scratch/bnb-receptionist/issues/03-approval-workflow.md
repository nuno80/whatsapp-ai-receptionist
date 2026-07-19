## What to build

The app has one WhatsApp Business number serving both guests and the four approvers. Approvers are detected by sender phone (`from` ∈ `authorized_approvers`) and routed to the approval path **before** the AI chat path; approver phones are never treated as guests (SPEC invariant #11).

A new approval module:
- Create a pending request (`create` / `cancel` / `modify`) with a short unique id and store it (`approval:{id}`).
- **Fan out** a summary WhatsApp message *from* the business number *to* each of the 4 approver phones (dates, guests, name, phone, total, request id, how to reply).
- **Atomic first-claim-wins** lock (`approval:claim:{id}`, SETNX). First valid approve/reject that wins the claim executes the side effect.
- On winner: run the calendar action, notify the guest of the outcome, notify the other approvers "gestita da {name}".
- Reply parsing: `OK <id>` / `NO <id>`; bare `OK` / `NO` allowed **only** when exactly one request is pending system-wide; otherwise reply with the pending list / ids (no claim).
- No auto-expiry — requests stay `pending` until an approver approves or rejects.

## Acceptance criteria

- [ ] Approver-originating messages are routed to the approval path before Giulia; approver phones never trigger guest booking intents
- [ ] Creating a request fans out a WhatsApp summary to all 4 approvers from the business number
- [ ] Concurrent `OK` from two approvers → exactly one wins the atomic claim; the loser gets "gestita da {name}"
- [ ] `OK <id>` / `NO <id>` parsed; bare `OK` / `NO` rejected with the pending id list when zero or multiple are pending
- [ ] A non-approver cannot claim; pending requests never auto-expire

## Blocked by

- #1 — Foundation: B&B config schema + pricing & min-stay rules
- #2 — Calendar stay model (Google Calendar)
