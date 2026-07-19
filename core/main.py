import json as json_lib
import logging
import os
from contextlib import asynccontextmanager
from datetime import date, time as dt_time

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse

from config.loader import load_config
from core.ai import extract_intent, get_ai_response, load_knowledge
from core.history import get_history
from core.transcribe import transcribe_audio
from core.whatsapp import WhatsAppClient, validate_webhook_signature
from modules.booking.calendar import CalendarClient
import stripe
from modules.approval.workflow import is_approver, handle_approval_message
from reminders.scheduler import send_reminders

logger = logging.getLogger(__name__)

CONFIG = load_config()
HISTORY = get_history()

WA = WhatsAppClient(
    phone_number_id=os.environ["WHATSAPP_PHONE_NUMBER_ID"],
    access_token=os.environ["WHATSAPP_ACCESS_TOKEN"],
)
APP_SECRET = os.environ["WHATSAPP_APP_SECRET"]
VERIFY_TOKEN = os.environ["WHATSAPP_VERIFY_TOKEN"]
INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "")
MP_WEBHOOK_SECRET = os.environ.get("MP_WEBHOOK_SECRET", "")

_calendar_client: CalendarClient | None = None
from modules.payments.stripe_client import StripeClient

_stripe_client: StripeClient | None = None
_pending_redis = None

# In-memory fallback for pending operations (used when Redis is not available)
_pending_modifications: dict[str, dict] = {}
_pending_cancellations: dict[str, list[dict]] = {}
_message_locks: dict[str, float] = {}  # phone -> lock expiry timestamp

# Keywords that indicate the user wants to modify an existing booking
_MODIFICATION_KEYWORDS = {"change", "modify", "move", "reschedule", "switch", "postpone", "cambiar", "modificar", "mover", "reprogramar"}


def _get_stripe_client():
    if not CONFIG.get("modules", {}).get("payments"):
        return None
    global _stripe_client
    if _stripe_client is None:
        from modules.payments.stripe_client import StripeClient
        _stripe_client = StripeClient()
    return _stripe_client


def _get_pending_payment_redis():
    global _pending_redis
    if _pending_redis is None:
        redis_url = os.environ.get("REDIS_URL")
        if redis_url:
            import redis
            _pending_redis = redis.from_url(redis_url, decode_responses=True)
    return _pending_redis


def _acquire_message_lock(phone: str, ttl: int = 15) -> bool:
    """Try to acquire a processing lock for this phone. Returns True if acquired."""
    r = _get_pending_payment_redis()
    if r:
        key = f"msg_lock:{phone}"
        return bool(r.set(key, "1", nx=True, ex=ttl))
    # In-memory fallback
    import time
    now = time.time()
    expiry = _message_locks.get(phone, 0)
    if now < expiry:
        return False  # Lock still held
    _message_locks[phone] = now + ttl
    return True


def _release_message_lock(phone: str):
    r = _get_pending_payment_redis()
    if r:
        r.delete(f"msg_lock:{phone}")
    else:
        _message_locks.pop(phone, None)


def _save_pending_modification(phone: str, event: dict, ttl: int = 600):
    """Store event pending modification (will be deleted when new booking is confirmed)."""
    r = _get_pending_payment_redis()
    if r:
        r.setex(f"pending_modification:{phone}", ttl, json_lib.dumps(event))
    else:
        _pending_modifications[phone] = event


def _get_pending_modification(phone: str) -> dict | None:
    r = _get_pending_payment_redis()
    if r:
        raw = r.get(f"pending_modification:{phone}")
        if raw:
            return json_lib.loads(raw)
        return None
    return _pending_modifications.get(phone)


def _delete_pending_modification(phone: str):
    r = _get_pending_payment_redis()
    if r:
        r.delete(f"pending_modification:{phone}")
    else:
        _pending_modifications.pop(phone, None)


def _save_pending_cancellation(phone: str, events: list[dict], ttl: int = 600):
    """Store events pending cancellation for this phone (10 min TTL)."""
    r = _get_pending_payment_redis()
    if r:
        r.setex(f"pending_cancellation:{phone}", ttl, json_lib.dumps(events))
    else:
        _pending_cancellations[phone] = events


def _get_pending_cancellation(phone: str) -> list[dict] | None:
    """Get events pending cancellation for this phone."""
    r = _get_pending_payment_redis()
    if r:
        raw = r.get(f"pending_cancellation:{phone}")
        if raw:
            return json_lib.loads(raw)
        return None
    return _pending_cancellations.get(phone)


def _delete_pending_cancellation(phone: str):
    r = _get_pending_payment_redis()
    if r:
        r.delete(f"pending_cancellation:{phone}")
    else:
        _pending_cancellations.pop(phone, None)


def _save_pending_payment(phone: str, data: dict, ttl: int = 1800):
    """Store pending payment keyed by phone (used as external_reference in MP)."""
    r = _get_pending_payment_redis()
    if r:
        r.setex(f"pending_payment:{phone}", ttl, json_lib.dumps(data))

def _get_guest_lang(phone: str) -> str:
    """Retrieve the guest's language from Redis or fallback memory."""
    r = _get_pending_payment_redis()
    if r:
        lang = r.get(f"guest_lang:{phone}")
        if lang:
            return lang
    return "it"

def _set_guest_lang(phone: str, lang: str):
    """Store the guest's language in Redis or fallback memory."""
    r = _get_pending_payment_redis()
    if r:
        r.set(f"guest_lang:{phone}", lang)

def _get_free_ranges(cal: CalendarClient) -> list[dict]:
    """Stub to get free ranges for the AI prompt. Real implementation depends on calendar sweep."""
    from datetime import date, timedelta
    today = date.today()
    return [{"start": (today + timedelta(days=1)).isoformat(), "end": (today + timedelta(days=3)).isoformat()}]

def _get_and_delete_pending_payment(payment: dict) -> dict | None:
    """Look up pending payment using external_reference from the MP payment object."""
    r = _get_pending_payment_redis()
    if not r:
        return None
    phone = payment.get("external_reference", "")
    if not phone:
        return None
    key = f"pending_payment:{phone}"
    raw = r.get(key)
    if raw:
        r.delete(key)
        return json_lib.loads(raw)
    return None


def _get_calendar_client() -> CalendarClient | None:
    if not CONFIG.get("modules", {}).get("booking"):
        return None
    global _calendar_client
    if _calendar_client is None:
        booking_cfg = CONFIG["booking"]
        _calendar_client = CalendarClient(
            calendar_id=booking_cfg["calendar_id"],
            calendar_owner_email=booking_cfg["calendar_owner_email"],
            timezone=CONFIG["client"].get("timezone", "UTC"),
        )
    return _calendar_client


def _find_service(service_name: str) -> dict | None:
    services = CONFIG.get("booking", {}).get("services", [])
    name = service_name.lower()
    # Exact match first
    for s in services:
        if s["name"].lower() == name:
            return s
    # Substring match: prioritize longest match to avoid partial matches (e.g. "Dental Cleaning" matching before "Cleaning + Checkup (bundle)")
    matches = []
    for s in services:
        s_lower = s["name"].lower()
        if name in s_lower or s_lower in name:
            matches.append(s)
    if matches:
        # Return the service with the longest name (most specific match)
        return max(matches, key=lambda s: len(s["name"]))
    logger.warning("Service not found: '%s'. Available: %s", service_name,
                   [s["name"] for s in services])
    return None


def _find_location(location_name: str) -> dict | None:
    locations = CONFIG.get("booking", {}).get("locations", [])
    name = location_name.lower()
    for loc in locations:
        if loc["name"].lower() == name:
            return loc
    # Substring match
    for loc in locations:
        loc_lower = loc["name"].lower()
        if name in loc_lower or loc_lower in name:
            return loc
    logger.warning("Location not found: '%s'. Available: %s", location_name,
                   [loc["name"] for loc in locations])
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def health():
    return {"status": "ok"}


@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403)


@app.post("/webhook")
async def receive_message(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not validate_webhook_signature(body, signature, APP_SECRET):
        raise HTTPException(status_code=403, detail="Invalid signature")

    data = await request.json()

    try:
        entry = data["entry"][0]
        change = entry["changes"][0]["value"]

        # Ignore status updates (delivered, read, etc.)
        if "statuses" in change:
            return Response(status_code=200)

        message = change["messages"][0]
        phone = message["from"]
        msg_type = message.get("type")

        if msg_type == "text":
            user_text = message["text"]["body"]
        elif msg_type == "audio":
            media_id = message["audio"]["id"]
            try:
                audio_bytes, mime_type = await WA.download_media(media_id)
                guest_lang = _get_guest_lang(phone)
                user_text = transcribe_audio(audio_bytes, mime_type, lang=guest_lang)
                logger.info("Audio transcribed for %s: %s", phone, user_text[:100])
            except Exception as e:
                logger.error("Audio transcription failed: %s", e)
                await WA.send_text(phone, "I couldn't process your audio. Could you send it as text instead?")
                return Response(status_code=200)
        else:
            await WA.send_text(phone, "I can only process text and audio messages for now.")
            return Response(status_code=200)

    except (KeyError, IndexError):
        return Response(status_code=200)

    # Intercept approver messages BEFORE the normal flow
    if is_approver(phone, CONFIG):
        r = _get_pending_payment_redis()
        if r:
            result = await handle_approval_message(r, CONFIG, WA, phone, user_text)
            if result != "ignored":
                return Response(status_code=200)

    # Prevent concurrent processing for the same phone number
    if not _acquire_message_lock(phone):
        logger.info("Message from %s skipped (already processing)", phone)
        # Still add to history so the next response has context
        HISTORY.add(phone, "user", user_text)
        return Response(status_code=200)

    try:
        await _process_message(phone, user_text)
    finally:
        _release_message_lock(phone)

    return Response(status_code=200)


async def _process_message(phone: str, user_text: str):
    """Process a single message with lock already held."""
    # Get conversation history
    history = HISTORY.get(phone)
    HISTORY.add(phone, "user", user_text)

    # Proactively detect modification intent from user text and save pending state
    # This ensures the state survives even if many messages pass before booking_confirmed
    if not _get_pending_modification(phone):
        words = set(user_text.lower().split())
        if words & _MODIFICATION_KEYWORDS:
            cal = _get_calendar_client()
            if cal:
                events = cal.find_upcoming_events_by_phone(phone)
                if events:
                    _save_pending_modification(phone, events[0])
                    logger.info("Proactive modification state saved for %s", phone)

    # Load language-specific knowledge
    guest_lang = _get_guest_lang(phone)
    knowledge = load_knowledge(guest_lang)

    cal = _get_calendar_client()
    free_ranges = _get_free_ranges(cal) if cal else []

    # Get AI response
    ai_response = get_ai_response(
        user_message=user_text,
        history=history,
        config=CONFIG,
        knowledge=knowledge,
        free_ranges=free_ranges,
        detected_lang=guest_lang
    )

    # Check for intent
    intent, visible_response = extract_intent(ai_response)

    if intent:
        if "lang" in intent:
            _set_guest_lang(phone, intent["lang"])
            
        if CONFIG.get("modules", {}).get("booking"):
            intent_type = intent.get("intent", "")
            logger.info("Intent detected: %s", intent)

            if intent_type == "booking_requested":
                await _handle_booking_requested(phone, intent, visible_response)
            elif intent_type == "cancellation_request":
                await _handle_cancellation_request(phone, visible_response)
            elif intent_type == "cancellation_confirmed":
                await _handle_cancellation_confirmed(phone, intent, visible_response)
            elif intent_type == "modification_request":
                await _handle_modification_request(phone, visible_response)
            elif intent_type == "modification_confirmed":
                await _handle_modification_confirmed(phone, intent, visible_response)
            else:
                HISTORY.add(phone, "assistant", visible_response or ai_response)
                await WA.send_text(phone, visible_response or ai_response)
        else:
            HISTORY.add(phone, "assistant", visible_response or ai_response)
            await WA.send_text(phone, visible_response or ai_response)
    else:
        HISTORY.add(phone, "assistant", ai_response)
        await WA.send_text(phone, ai_response)


def _conversation_suggests_modification(history: list[dict]) -> bool:
    """Check recent conversation history for modification-related keywords."""
    # Look at the last 6 messages (3 exchanges) for modification signals
    recent = history[-6:] if len(history) > 6 else history
    for msg in recent:
        if msg["role"] == "user":
            words = set(msg["content"].lower().split())
            if words & _MODIFICATION_KEYWORDS:
                return True
    return False


async def _handle_booking_requested(phone: str, intent: dict, visible_response: str):
    """Process a requested booking intent."""
    cal = _get_calendar_client()
    if cal is None:
        HISTORY.add(phone, "assistant", visible_response)
        await WA.send_text(phone, visible_response)
        return

    logger.info("[INTENT] %s", intent)
    
    try:
        checkin_date = date.fromisoformat(intent["checkin"])
        checkout_date = date.fromisoformat(intent["checkout"])
    except (ValueError, KeyError) as e:
        logger.warning("Invalid date in intent: %s", e)
        error_msg = "C'è stato un problema con le date. Puoi riprovare?"
        HISTORY.add(phone, "assistant", error_msg)
        await WA.send_text(phone, error_msg)
        return

    import pytz
    from datetime import datetime
    timezone = pytz.timezone(CONFIG["client"]["timezone"])
    today = datetime.now(timezone).date()
    
    if checkin_date < today:
        error_msg = "La data di check-in non può essere nel passato. Quali altre date cerchi?"
        HISTORY.add(phone, "assistant", error_msg)
        await WA.send_text(phone, error_msg)
        return
        
    if checkout_date <= checkin_date:
        error_msg = "La data di check-out deve essere successiva al check-in."
        HISTORY.add(phone, "assistant", error_msg)
        await WA.send_text(phone, error_msg)
        return
        
    nights = (checkout_date - checkin_date).days
    min_stay_periods = CONFIG["booking"].get("minimum_stay_periods", [])
    from modules.booking.pricing import min_nights_required
    min_stay = min_nights_required(checkin_date, checkout_date, min_stay_periods)
    if nights < min_stay:
        error_msg = f"Il soggiorno minimo in questo periodo è di {min_stay} notti."
        HISTORY.add(phone, "assistant", error_msg)
        await WA.send_text(phone, error_msg)
        return
        
    guests = intent.get("guests", 1)
    max_guests = CONFIG["booking"].get("max_guests", 2)
    if guests > max_guests:
        error_msg = f"Possiamo ospitare al massimo {max_guests} persone."
        HISTORY.add(phone, "assistant", error_msg)
        await WA.send_text(phone, error_msg)
        return
        
    if not cal.is_range_available(checkin_date, checkout_date):
        error_msg = f"Purtroppo le date dal {checkin_date.strftime('%d/%m')} al {checkout_date.strftime('%d/%m')} non sono disponibili. Vuoi controllare altri giorni?"
        HISTORY.add(phone, "assistant", error_msg)
        await WA.send_text(phone, error_msg)
        return
        
    # Calculate price
    from modules.booking.pricing import price_for_stay
    pricing_periods = CONFIG["booking"].get("pricing_periods", [])
    try:
        total_price = price_for_stay(checkin_date, checkout_date, pricing_periods)
    except Exception as e:
        logger.error("Pricing error: %s", e)
        error_msg = "Non sono riuscito a calcolare il prezzo per queste date. Per favore riprova o contattaci."
        HISTORY.add(phone, "assistant", error_msg)
        await WA.send_text(phone, error_msg)
        return
        
    cal.lock_range(checkin_date, checkout_date)
    
    from modules.approval.workflow import create_request
    redis_client = _get_pending_payment_redis()
    
    from core.phone import normalize_phone
    guest_phone = normalize_phone(phone)

    request_data = {
        "type": "create",
        "guest_phone": guest_phone,
        "guest_name": intent.get("user_name", "Ospite"),
        "checkin": checkin_date.isoformat(),
        "checkout": checkout_date.isoformat(),
        "guests": guests,
        "total": total_price,
        "lang": intent.get("lang", "it")
    }
    
    await create_request(redis_client, CONFIG, WA, request_data)
    
    # Send pending message (we do not tell them confirmed)
    HISTORY.add(phone, "assistant", visible_response)
    await WA.send_text(phone, visible_response)


@app.post("/payments/webhook")
async def payment_webhook(request: Request):
    body = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    if secret:
        from modules.payments.stripe_client import validate_stripe_signature
        if not validate_stripe_signature(body, sig_header, secret):
            raise HTTPException(status_code=403, detail="Invalid Stripe signature")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if data.get("type") != "checkout.session.completed":
        return Response(status_code=200)

    session = data.get("data", {}).get("object", {})
    payment_status = session.get("payment_status")
    
    if payment_status != "paid":
        return Response(status_code=200)

    reference = session.get("client_reference_id")
    if not reference:
        return Response(status_code=200)

    # Reference is the Stay/Event ID
    cal = _get_calendar_client()
    if cal:
        # Mark as paid and get guest phone
        try:
            event = cal._service.events().get(
                calendarId=cal.calendar_id, 
                eventId=reference
            ).execute()
            
            # Find phone from description or extendedProperties
            guest_phone = None
            if "extendedProperties" in event and "private" in event["extendedProperties"]:
                guest_phone = event["extendedProperties"]["private"].get("guest_phone")
                
            # Update payment state in title
            summary = event.get("summary", "")
            if "[PENDING PAYMENT]" in summary:
                new_summary = summary.replace("[PENDING PAYMENT]", "").strip()
                cal._service.events().patch(
                    calendarId=cal.calendar_id,
                    eventId=reference,
                    body={"summary": new_summary}
                ).execute()

            if guest_phone:
                await WA.send_text(
                    guest_phone, 
                    "Il tuo pagamento è stato ricevuto con successo. La prenotazione è ora completamente confermata! Grazie."
                )
        except Exception as e:
            logger.error("Failed to process payment for event %s: %s", reference, e)

    return Response(status_code=200)


async def _handle_cancellation_request(phone: str, visible_response: str):
    """User wants to cancel — find their upcoming events."""
    cal = _get_calendar_client()
    if cal is None:
        await WA.send_text(phone, "The booking module is not available.")
        return

    events = cal.find_upcoming_events_by_phone(phone)

    if not events:
        msg = "I couldn't find any appointments booked with your number. Is there anything else I can help with?"
        HISTORY.add(phone, "assistant", msg)
        await WA.send_text(phone, msg)
        return

    _save_pending_cancellation(phone, events)

    if len(events) == 1:
        e = events[0]
        msg = (
            f"{visible_response}\n\n"
            f"I found this appointment:\n"
            f"*{e['summary']}*\n"
            f"Date: {e['date']}\n"
            f"Time: {e['time']}\n"
            f"Location: {e['location']}\n\n"
            f"Do you confirm you want to cancel it?"
        )
    else:
        lines = [f"{visible_response}\n\nI found these appointments:\n"]
        for i, e in enumerate(events, 1):
            lines.append(
                f"{i}. *{e['summary']}* — {e['date']} at {e['time']} at {e['location']}"
            )
        lines.append("\nWhich one would you like to cancel?")
        msg = "\n".join(lines)

    HISTORY.add(phone, "assistant", msg)
    await WA.send_text(phone, msg)


async def _handle_cancellation_confirmed(phone: str, intent: dict, visible_response: str):
    """User confirmed cancellation — request approval."""
    cal = _get_calendar_client()
    if cal is None:
        await WA.send_text(phone, "The booking module is not available.")
        return

    events = _get_pending_cancellation(phone)
    if not events:
        msg = "I couldn't find an active cancellation request. Would you like to cancel an appointment? Let me know and I'll look up your bookings."
        HISTORY.add(phone, "assistant", msg)
        await WA.send_text(phone, msg)
        return

    event_index = intent.get("event_index", 1)
    try:
        event_index = int(event_index)
    except (TypeError, ValueError):
        event_index = 1

    if event_index < 1 or event_index > len(events):
        msg = f"Invalid number. Please choose a number from 1 to {len(events)}."
        HISTORY.add(phone, "assistant", msg)
        await WA.send_text(phone, msg)
        return

    event = events[event_index - 1]

    try:
        from modules.approval.workflow import create_request
        redis_client = _get_pending_payment_redis()
        
        # Create cancellation approval request
        # Parse the checkin date from the start time or use the English date string loosely
        # For simplicity we extract it from description which may have what we need, or from 'date'
        from datetime import datetime
        import pytz
        tz = pytz.timezone(CONFIG["client"]["timezone"])
        # Format date as human-readable English was done in calendar list. Let's just pass the string.
        
        request_data = {
            "type": "cancel",
            "guest_phone": phone,
            "guest_name": "Ospite",  # Could extract from summary
            "event_id": event["id"],
            "summary": event.get("summary", ""),
            "dates": f"{event.get('date')} at {event.get('time')}",
            "checkin_str": event.get("date"), # Need enough to check free cancellation policy later
            "total": 0, # Don't care for cancel display
            "lang": _get_guest_lang(phone)
        }
        
        await create_request(redis_client, CONFIG, WA, request_data)
        
        _delete_pending_cancellation(phone)
        
        msg = (
            f"La tua richiesta di cancellazione per *{event['summary']}* del {event['date']} è stata inviata per l'approvazione. "
            f"Ti avviseremo non appena verrà confermata."
        )
        logger.info("Cancellation request created for event: %s for phone %s", event["id"], phone)
    except Exception as e:
        logger.error("Failed to create cancellation request: %s", e)
        msg = "C'è stato un problema nel processare la richiesta. Per favore contattaci direttamente."

    HISTORY.add(phone, "assistant", msg)
    await WA.send_text(phone, msg)


async def _handle_modification_request(phone: str, visible_response: str):
    """User wants to modify — show their events and ask for new date.
    The old event is NOT deleted yet. It gets deleted when the new booking is confirmed."""
    cal = _get_calendar_client()
    if cal is None:
        await WA.send_text(phone, "The booking module is not available.")
        return

    events = cal.find_upcoming_events_by_phone(phone)

    if not events:
        msg = "I couldn't find any appointments booked with your number. Would you like to book a new one?"
        HISTORY.add(phone, "assistant", msg)
        await WA.send_text(phone, msg)
        return

    if len(events) == 1:
        e = events[0]
        # Store the event to delete later when the new booking is confirmed
        _save_pending_modification(phone, e)
        msg = (
            f"{visible_response}\n\n"
            f"I found your appointment:\n"
            f"*{e['summary']}*\n"
            f"Date: {e['date']}\n"
            f"Time: {e['time']}\n"
            f"Location: {e['location']}\n\n"
            f"What date and time would you like to change it to?"
        )
    else:
        # Instead of pending_cancellation, we use pending_modification logic for the index
        _save_pending_cancellation(phone, events)
        lines = [f"{visible_response}\n\nI found these appointments:\n"]
        for i, e in enumerate(events, 1):
            lines.append(
                f"{i}. *{e['summary']}* — {e['date']} at {e['time']} at {e['location']}"
            )
        lines.append("\nWhich one would you like to modify?")
        msg = "\n".join(lines)

    HISTORY.add(phone, "assistant", msg)
    await WA.send_text(phone, msg)


async def _handle_modification_confirmed(phone: str, intent: dict, visible_response: str):
    """User confirmed their new modification details — send to approvers."""
    cal = _get_calendar_client()
    if cal is None:
        await WA.send_text(phone, "The booking module is not available.")
        return

    # Check if they are answering the "which one" question
    events = _get_pending_cancellation(phone)
    if events and "event_index" in intent:
        event_index = intent.get("event_index", 1)
        try:
            event_index = int(event_index)
        except (TypeError, ValueError):
            event_index = 1

        if event_index < 1 or event_index > len(events):
            msg = f"Invalid number. Please choose a number from 1 to {len(events)}."
            HISTORY.add(phone, "assistant", msg)
            await WA.send_text(phone, msg)
            return

        event = events[event_index - 1]
        _delete_pending_cancellation(phone)
        _save_pending_modification(phone, event)

        msg = (
            f"Sure, let's modify *{event['summary']}* on {event['date']} at {event['time']}.\n\n"
            f"What date and time would you like to change it to?"
        )
        HISTORY.add(phone, "assistant", msg)
        await WA.send_text(phone, msg)
        return

    # User provided new dates
    old_event = _get_pending_modification(phone)
    if not old_event:
        msg = "I couldn't find an active modification request. Would you like to modify an appointment?"
        HISTORY.add(phone, "assistant", msg)
        await WA.send_text(phone, msg)
        return

    try:
        checkin_date = date.fromisoformat(intent["checkin"])
        checkout_date = date.fromisoformat(intent["checkout"])
    except (ValueError, KeyError) as e:
        logger.warning("Invalid date in intent: %s", e)
        error_msg = "C'è stato un problema con le date. Puoi riprovare?"
        HISTORY.add(phone, "assistant", error_msg)
        await WA.send_text(phone, error_msg)
        return

    import pytz
    from datetime import datetime
    timezone = pytz.timezone(CONFIG["client"]["timezone"])
    today = datetime.now(timezone).date()
    
    if checkin_date < today:
        error_msg = "La data di check-in non può essere nel passato. Quali altre date cerchi?"
        HISTORY.add(phone, "assistant", error_msg)
        await WA.send_text(phone, error_msg)
        return
        
    if checkout_date <= checkin_date:
        error_msg = "La data di check-out deve essere successiva al check-in."
        HISTORY.add(phone, "assistant", error_msg)
        await WA.send_text(phone, error_msg)
        return

    # Verify new availability excluding old event
    if not cal.is_range_available(checkin_date, checkout_date, exclude_event_id=old_event["id"]):
        error_msg = f"Purtroppo le date dal {checkin_date.strftime('%d/%m')} al {checkout_date.strftime('%d/%m')} non sono disponibili. Vuoi controllare altri giorni?"
        HISTORY.add(phone, "assistant", error_msg)
        await WA.send_text(phone, error_msg)
        return

    guests = intent.get("guests", 1)
    
    from modules.booking.pricing import price_for_stay
    pricing_periods = CONFIG["booking"].get("pricing_periods", [])
    try:
        total_price = price_for_stay(checkin_date, checkout_date, pricing_periods)
    except Exception as e:
        logger.error("Pricing error: %s", e)
        error_msg = "Non sono riuscito a calcolare il prezzo per queste date. Per favore riprova o contattaci."
        HISTORY.add(phone, "assistant", error_msg)
        await WA.send_text(phone, error_msg)
        return

    cal.lock_range(checkin_date, checkout_date)

    try:
        from modules.approval.workflow import create_request
        redis_client = _get_pending_payment_redis()
        
        request_data = {
            "type": "modify",
            "guest_phone": phone,
            "guest_name": intent.get("user_name", "Ospite"),
            "event_id": old_event["id"],
            "checkin": checkin_date.isoformat(),
            "checkout": checkout_date.isoformat(),
            "guests": guests,
            "total": total_price,
            "lang": intent.get("lang", "it")
        }
        
        await create_request(redis_client, CONFIG, WA, request_data)
        _delete_pending_modification(phone)
        
        msg = (
            f"La tua richiesta di modifica per il soggiorno dal {checkin_date.strftime('%d/%m')} "
            f"al {checkout_date.strftime('%d/%m')} (totale: €{total_price}) è stata inviata per l'approvazione."
        )
    except Exception as e:
        logger.error("Failed to create modification request: %s", e)
        msg = "C'è stato un problema nel processare la richiesta. Per favore contattaci direttamente."

    HISTORY.add(phone, "assistant", msg)
    await WA.send_text(phone, msg)


@app.post("/internal/send-reminders")
async def trigger_reminders(request: Request):
    secret = request.headers.get("X-Internal-Secret", "")
    if secret != INTERNAL_SECRET:
        raise HTTPException(status_code=403)

    cal = _get_calendar_client()
    if cal is None:
        return {"sent": 0, "error": "booking module disabled"}

    sent = await send_reminders(CONFIG, cal._service, WA)
    return {"sent": sent}
