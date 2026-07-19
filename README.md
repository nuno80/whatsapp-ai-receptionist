<h1 align="center">WhatsApp AI Receptionist for B&B</h1>

**Your guests are messaging you on WhatsApp anyway. This bot answers them.**

A specialized WhatsApp AI receptionist for Bed & Breakfasts and short-term rentals. It handles conversational booking inquiries, checks real-time availability in Google Calendar, creates pending approval requests for the owners, and manages the full lifecycle (create, modify, cancel) with policy enforcement and multi-language support (IT/EN/ES/FR/DE).

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![Tests](https://github.com/nuno80/whatsapp-ai-receptionist/actions/workflows/tests.yml/badge.svg)
![License](https://img.shields.io/badge/license-MIT-green)

---

## What it does

| Capability | How |
|---|---|
| **Conversational booking** | Natural language via WhatsApp, powered by Claude 3.5 Sonnet |
| **Real-time availability** | Google Calendar freebusy integration for consecutive night stays |
| **Atomic Approvals** | All requests are routed to human owners for approval via WhatsApp before confirming |
| **Full lifecycle** | Create, cancel, and modify stays |
| **Voice messages** | Audio transcribed via OpenAI Whisper |
| **Multi-Language** | Detects user language (IT, EN, ES, FR, DE) and switches knowledge base and replies dynamically |
| **Pricing Rules** | Built-in rules engine for nightly pricing, date periods, and minimum stays |
| **Multi-client ready** | YAML config + knowledge base per business, no code changes |
| **Resilient state** | Redis in production, in-memory fallback for development |

---

## How it works

```text
Guest sends WhatsApp message
        │
        ▼
┌─────────────────┐
│  FastAPI webhook │ ◄── validates HMAC signature
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌───────────────────────┐
│   Claude AI     │ ◄───│  Knowledge base       │
│  (conversation) │     │  config.yaml + IT/EN/..│
└────────┬────────┘     └───────────────────────┘
         │
         │ extracts structured stay intent
         ▼
┌─────────────────┐
│ Google Calendar  │ ◄── real-time freebusy check
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Approval System  │ ◄── Fans out to 4 owner phones
└────────┬────────┘
         │
         │ First owner replies "OK <id>"
         ▼
   ┌─────┴──────┐
   │            │
   ▼            ▼
┌──────┐  ┌──────────┐
│ Book │  │ Cancel/  │
│      │  │ Modify   │
└──┬───┘  └────┬─────┘
   │           │
   ▼           ▼
   Confirmation via WhatsApp
```

---

## Design principles

- **Human-in-the-loop.** All booking creation, modification, and cancellation requests require explicit approval from the host(s).
- **No frameworks for the sake of frameworks.** Plain FastAPI with direct Anthropic SDK calls. No LangChain, no LangGraph. The problem is solved by direct API calls.
- **Config-driven, not code-driven.** New clients are onboarded by editing `config.yaml` and `knowledge/{lang}.txt`. No code changes, no admin panel.
- **Works offline from Redis.** Every stateful component has a Redis backend and an in-memory fallback. Run locally with zero infrastructure.

See [DECISIONS.md](DECISIONS.md) for the full rationale behind each technical choice.

---

## Quick start

### 1. Clone and install

```bash
git clone https://github.com/nuno80/whatsapp-ai-receptionist.git
cd whatsapp-ai-receptionist
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your API keys
```

Required:
- `ANTHROPIC_API_KEY` -- [Get one here](https://console.anthropic.com/)
- `WHATSAPP_ACCESS_TOKEN` + `WHATSAPP_PHONE_NUMBER_ID` + `WHATSAPP_APP_SECRET` -- [Meta Developer Portal](https://developers.facebook.com/)
- `WHATSAPP_VERIFY_TOKEN` -- any string you choose (must match webhook config)
- `REDIS_URL` -- required for atomic approval locks

For booking (required):
- `GOOGLE_SERVICE_ACCOUNT_JSON` -- base64-encoded Google service account credentials
- `GOOGLE_CALENDAR_ID` + `GOOGLE_CALENDAR_OWNER_EMAIL`

Edit `config.yaml` with your business details:
- **`authorized_approvers`**: list of phone numbers (e.g. `+393331234567`) that receive approval requests.
- **`bot_persona`**: controls tone and whether it declares itself as AI.
- **`booking`**: max guests, cancellation policies, pricing periods, and minimum stay periods.

Populate the knowledge base by editing `knowledge/it.txt`, `knowledge/en.txt`, etc.

### 3. Run

```bash
uvicorn core.main:app --reload
```

### 4. Expose for WhatsApp

Use [ngrok](https://ngrok.com/) for local development:

```bash
ngrok http 8000
```

Set the webhook URL in [Meta Developer Portal](https://developers.facebook.com/) -> WhatsApp -> Configuration:
- Callback URL: `https://your-ngrok-url.ngrok.io/webhook`
- Verify token: same as your `WHATSAPP_VERIFY_TOKEN`

---

## Configuration

### config.yaml

```yaml
client:
  name: "B&B Roma Centrale"
  timezone: "Europe/Rome"

modules:
  booking: true
  payments: false
  reminders: false
  ota_sync: false

bot_persona:
  name: "Giulia"
  tone: "cordiale-professionale"
  declares_as_ai: true

authorized_approvers:
  - phone: "+393331234567"
    name: "Marco"
  - phone: "+393337654321"
    name: "Anna"

booking:
  calendar_id: "${GOOGLE_CALENDAR_ID}"
  calendar_owner_email: "${GOOGLE_CALENDAR_OWNER_EMAIL}"
  max_guests: 2
  checkin_time: "15:00"
  checkout_time: "10:00"
  cancellation_policy:
    free_cancellation_days_before: 7
  pricing_periods:
    - start_date: "2026-01-01"
      end_date: "2026-12-31"
      price_per_night: 120
  minimum_stay_periods:
    - start_date: "2026-01-01"
      end_date: "2026-12-31"
      min_nights: 2
```

### knowledge/

Free-text knowledge base about the business divided by language (`it.txt`, `en.txt`, etc). The AI uses this to answer questions. Write it like you'd explain the business to a new receptionist.

---

## Testing

```bash
pytest tests/ -v
```

Tests cover all modules -- webhook handling, AI intent extraction, pricing rules, approval flow, calendar operations, payment flows, and configuration.

---

## Architecture

```text
whatsapp-ai-receptionist/
├── core/
│   ├── main.py          # FastAPI app, webhook handlers, intent routing
│   ├── ai.py            # Claude integration, system prompt, intent extraction
│   ├── whatsapp.py      # WhatsApp Cloud API client
│   ├── transcribe.py    # Whisper audio transcription
│   ├── history.py       # Conversation history (Redis / in-memory)
│   └── phone.py         # Phone number normalization for Italy/International
├── config/
│   └── loader.py        # YAML config with ${ENV_VAR} substitution
├── modules/
│   ├── approval/        # First-claim-wins atomic approver routing
│   │   └── workflow.py
│   ├── booking/
│   │   ├── calendar.py  # Google Calendar range locks and sync
│   │   └── pricing.py   # Date-based rules engine for pricing/min-stay
│   └── payments/
│       └── mercadopago.py
├── reminders/
│   └── scheduler.py     # 24h reminder sender
├── knowledge/
│   └── it.txt, en.txt...# Multi-language business knowledge
├── config.yaml          # Per-client configuration
└── tests/               # Unit and integration tests
```

---

## Contributing

Contributions are welcome. The codebase is intentionally small and direct -- please keep it that way.

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Make sure tests pass (`pytest tests/ -v`)
4. Open a pull request

No issue template, no CLA. Just describe what you changed and why.

---

## Community

- **Issues**: [GitHub Issues](https://github.com/nuno80/whatsapp-ai-receptionist/issues) -- bug reports, feature requests, questions
- **Discussions**: [GitHub Discussions](https://github.com/nuno80/whatsapp-ai-receptionist/discussions) -- ideas, show & tell, general chat

---

## License

MIT
