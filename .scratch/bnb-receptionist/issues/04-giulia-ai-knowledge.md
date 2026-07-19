## What to build

The AI presents as **Giulia**, a virtual assistant of the B&B: cordiale-professionale tone, WhatsApp formatting only (single `*` bold, no markdown headings), and explicitly states it is a virtual assistant (not a human host) at least once early in a conversation and when asked. Persona comes from `bot_persona` config.

- Stay-shaped intent JSON: `booking_requested` / cancel / modify with `checkin`, `checkout`, `guests`, `user_name`, `lang` (old `service` / `location` / `time` fields gone). Intent naming means "ready for approval", never "confirmed".
- Pre-calculated **free date ranges** injected into the prompt (same anti-hallucination idea as the current next-dates injection); Giulia may only offer dates the server validates (server validation always wins).
- Language constrained to **IT / EN / ES / FR / DE**; reply in the guest's detected language; load `knowledge/{lang}.txt` with fallback `knowledge/it.txt`; **no machine translation**.
- Model switched to **Claude Sonnet 5** class (`claude-sonnet-5` or exact shipping id).
- Five knowledge stub files created (`it`, `en`, `es`, `fr`, `de`).
- Voice-note transcription uses the **guest's detected language** (fallback Italian for a Rome B&B), not a hardcoded language.

## Acceptance criteria

- [ ] Giulia persona from config; explicitly states it's a virtual assistant; WhatsApp formatting only
- [ ] Intent JSON carries `checkin` / `checkout` / `guests` / `user_name` / `lang`; old service/location/time fields gone; never claims "confirmed" pre-approval
- [ ] Free date ranges pre-calculated and injected; Giulia only offers dates the server validates
- [ ] Replies in the guest's detected language among IT/EN/ES/FR/DE; loads `knowledge/{lang}.txt` with `it` fallback; no translation
- [ ] Model is Claude Sonnet 5 class; voice notes transcribed in the guest's language (fallback IT)
- [ ] Five knowledge stub files created

## Blocked by

- #1 — Foundation: B&B config schema + pricing & min-stay rules
- #2 — Calendar stay model (Google Calendar)
