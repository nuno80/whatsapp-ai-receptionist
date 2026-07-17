# Project context — WhatsApp AI Receptionist

## What it does

**WhatsApp AI Receptionist** is a Python/FastAPI service that acts as a virtual receptionist for service businesses (dentists, salons, physiotherapists, etc.) over WhatsApp.

Clients message on WhatsApp; the bot:

1. **Answers questions** using a free-text knowledge base (`knowledge/client.txt`) and business config.
2. **Books, cancels, and reschedules** appointments against **Google Calendar** (real-time availability + slot locking).
3. **Transcribes voice notes** via OpenAI Whisper so audio works like text.
4. **Sends reminders** (typically 24h before) via WhatsApp when enabled.
5. **Optionally collects payment** through Mercado Pago (checkout link + payment webhook).

Configuration is **YAML + text**, not a database: onboard a business by editing `config.yaml` and `knowledge/client.txt`. Modules (booking, payments, reminders) can be toggled in config.

### High-level message flow

```
WhatsApp message
    → FastAPI /webhook (HMAC signature check)
    → optional audio transcription
    → per-phone lock (no concurrent double-processing)
    → conversation history (Redis or in-memory)
    → Claude (Haiku) reply + embedded JSON intent
    → intent routing (book / cancel / modify / chat)
    → Google Calendar / Mercado Pago as needed
    → reply via WhatsApp Cloud API
```

### HTTP endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/` | Health check |
| `GET` | `/webhook` | Meta WhatsApp webhook verification |
| `POST` | `/webhook` | Incoming WhatsApp messages |
| `POST` | `/payments/webhook` | Mercado Pago payment notifications |
| `POST` | `/internal/send-reminders` | Trigger reminders (cron / Railway) |

### Stack

- **Runtime:** Python 3.12+, FastAPI, Uvicorn  
- **AI:** Anthropic Claude Haiku (`core/ai.py`) for chat + structured intent in the reply  
- **Messaging:** WhatsApp Cloud API (Meta Graph API)  
- **Calendar:** Google Calendar API (service account)  
- **State:** Redis when available; in-memory fallback for local dev  
- **Payments (optional):** Mercado Pago SDK  
- **Voice:** OpenAI Whisper  
- **Deploy:** Railway (`railway.toml`) or any host that runs Uvicorn  

Design choices and trade-offs are documented in `DECISIONS.md` (no LangChain, intent-in-reply vs tool calling, YAML vs DB, dual Redis/memory backends, etc.).

---

## How it is structured

The real application lives under this repo root (folder `whatsapp-ai-receptionist/` if your workspace parent wraps the clone).

Architecture is intentionally **small and direct**:

- **`core/`** — app entrypoint, AI, WhatsApp, history, transcription, phone helpers  
- **`config/`** — load `config.yaml` with `${ENV_VAR}` substitution  
- **`modules/`** — optional product features (booking, payments)  
- **`reminders/`** — scheduled reminder sender  
- **`knowledge/`** — business knowledge base for the AI  
- **`tests/`** — pytest suite for webhooks, AI, calendar, payments, etc.  
- **Root config/docs** — `config.yaml`, `requirements.txt`, README, deploy/CI  

Feature flags in `config.yaml` under `modules:` gate booking, payments, and reminders without code changes.

---

## Directory and file guide

### `core/` — application heart

| File | Role |
|------|------|
| `main.py` | FastAPI app: webhooks, message processing, intent routing (book/cancel/modify), pending state (modifications, cancellations, payments), message locks |
| `ai.py` | Claude client, system prompt (config + knowledge + pre-calculated dates), chat replies, regex extraction of booking intent JSON |
| `whatsapp.py` | WhatsApp Cloud API client (send text, download media) + webhook HMAC validation |
| `history.py` | Per-phone conversation history (`RedisHistory` / `InMemoryHistory`, capped message window) |
| `transcribe.py` | Audio → text via Whisper |
| `phone.py` | Phone number normalization for WhatsApp API |
| `__init__.py` | Package marker |

### `config/` — configuration loading

| File | Role |
|------|------|
| `loader.py` | Reads `config.yaml`, recursively substitutes `${VAR}` from environment, raises `ConfigError` if missing |
| `__init__.py` | Package marker |

Root **`config.yaml`** (not inside this package) holds the live business settings: client name/timezone, module toggles, WhatsApp IDs, booking hours/services/locations/policy, payments sandbox, reminder template.

### `modules/` — optional feature modules

#### `modules/booking/`

| File | Role |
|------|------|
| `calendar.py` | `CalendarClient`: Google Calendar CRUD, free slots, slot locking (Redis/memory), find events by phone |
| `__init__.py` | Package marker |

#### `modules/payments/`

| File | Role |
|------|------|
| `mercadopago.py` | Mercado Pago preference/checkout creation, webhook signature validation |
| `__init__.py` | Package marker |

### `reminders/`

| File | Role |
|------|------|
| `scheduler.py` | Loads tomorrow’s calendar events and sends WhatsApp reminders from the configured template |
| `__init__.py` | Package marker |

Triggered by authenticated `POST /internal/send-reminders` (e.g. external cron).

### `knowledge/`

| File | Role |
|------|------|
| `client.txt` | Free-text business knowledge (services, professional bio, locations, FAQs). Injected into the AI system prompt |

### `tests/`

Pytest suite (`pytest.ini` at root). Includes:

- `conftest.py` — shared fixtures  
- `test_main.py` — webhook / routing  
- `test_ai.py` — AI / intent  
- `test_whatsapp.py`, `test_history.py`, `test_phone.py`, `test_config.py`  
- `test_calendar.py`, `test_reminders.py`  
- `test_mercadopago.py`, `test_payment_webhook.py`  

Run: `pytest tests/ -v`

### `public/`

| Path | Role |
|------|------|
| `screenshots/` | README demo images (booking and cancel flows) |

### `.github/workflows/`

| File | Role |
|------|------|
| `tests.yml` | CI test workflow |
| `release.yml` | Release workflow |

### Root files (repo root)

| File | Role |
|------|------|
| `config.yaml` | Per-business configuration |
| `requirements.txt` | Python dependencies |
| `pytest.ini` | Pytest settings |
| `railway.toml` | Railway deploy config |
| `.env.example` | Environment variable template (API keys, tokens, Redis, Google, MP) |
| `README.md` | Product overview, setup, architecture, deploy |
| `DECISIONS.md` | Architecture decision records |
| `LICENSE` | MIT |
| `.gitignore` | Git ignore rules |
| `contect.md` | This context summary |

---

## Mental model for contributors

1. **Inbound path** always hits `core/main.py` webhooks.  
2. **Conversation quality** is driven by `core/ai.py` + `knowledge/client.txt` + `config.yaml`.  
3. **Side effects** (calendar, payments, reminders) live under `modules/` and `reminders/`, enabled by config flags.  
4. **State** prefers Redis in production; everything important degrades to in-memory for local runs.  
5. **No heavy agent framework** — keep changes plain FastAPI + direct SDK calls unless complexity truly requires more.

For deeper “why”, read `DECISIONS.md`. For setup and env vars, read `README.md` and `.env.example`.
