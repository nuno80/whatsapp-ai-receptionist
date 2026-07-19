## What to build

`docker compose up` runs the app + Redis behind a **Caddy** HTTPS reverse proxy exposing the Meta WhatsApp webhook and the Stripe webhook on a public domain (required for Meta + Stripe webhooks). Railway is no longer the primary deploy path. An ops checklist (not code) documents: WhatsApp Business app setup, DNS, Google service account, Stripe webhook endpoint, and VPS env secrets.

## Acceptance criteria

- [ ] `docker compose up` runs app + redis; Caddy terminates TLS for the public domain
- [ ] Meta WhatsApp webhook and Stripe webhook reachable over HTTPS
- [ ] Railway is no longer the primary deploy path
- [ ] Ops checklist documents WA Business app, DNS, Google SA, Stripe webhook endpoint, VPS secrets

## Blocked by

- #8 — Stripe payments
- #9 — Reminders
- #10 — OTA iCal import
