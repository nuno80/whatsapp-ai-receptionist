import json
import random
import string
import redis.asyncio as redis
from datetime import date
from modules.booking.calendar import CalendarClient

def _get_calendar_client(config: dict) -> CalendarClient | None:
    booking_config = config.get("booking", {})
    calendar_id = booking_config.get("calendar_id")
    calendar_owner = booking_config.get("calendar_owner_email")
    if calendar_id and calendar_owner:
        return CalendarClient(
            calendar_id=calendar_id,
            calendar_owner_email=calendar_owner,
            timezone=config.get("client", {}).get("timezone", "UTC")
        )
    return None

def is_approver(phone: str, config: dict) -> str | None:
    for approver in config.get("authorized_approvers", []):
        if approver["phone"] == phone:
            return approver["name"]
    return None

async def get_pending_requests(redis_client: redis.Redis) -> list[str]:
    keys = await redis_client.keys("approval:*")
    # Filter out claim keys
    req_keys = [k.decode('utf-8') if isinstance(k, bytes) else k for k in keys if b"claim" not in (k if isinstance(k, bytes) else k.encode('utf-8'))]
    return [k.replace("approval:", "") for k in req_keys]

async def create_request(redis_client: redis.Redis, config: dict, whatsapp_client, data: dict) -> str:
    req_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
    await redis_client.set(f"approval:{req_id}", json.dumps(data))
    
    text = (
        f"Nuova richiesta {req_id} ({data.get('type')}):\n"
        f"Da: {data.get('guest_name')} ({data.get('guest_phone')})\n"
        f"Dal: {data.get('checkin', data.get('dates'))} al {data.get('checkout', '')}\n"
        f"Ospiti: {data.get('guests', 1)}\n"
        f"Totale: {data.get('total')}\n\n"
        f"Rispondi con OK {req_id} o NO {req_id}"
    )
    
    for approver in config.get("authorized_approvers", []):
        await whatsapp_client.send_message(to=approver["phone"], text=text)
        
    return req_id

async def handle_approval_message(redis_client: redis.Redis, config: dict, whatsapp_client, phone: str, text: str) -> str:
    approver_name = is_approver(phone, config)
    if not approver_name:
        return "ignored"
        
    text = text.strip().upper()
    parts = text.split()
    action = parts[0]
    
    if action not in ["OK", "NO"]:
        return "ignored"
        
    pending = await get_pending_requests(redis_client)
    
    req_id = None
    if len(parts) > 1:
        req_id = parts[1].lower()
    else:
        if len(pending) == 1:
            req_id = pending[0]
        else:
            list_text = "\n".join([f"- {i}" for i in pending])
            msg = f"Ci sono più richieste in attesa. Rispondi con OK <id> o NO <id>:\n{list_text}"
            await whatsapp_client.send_message(to=phone, text=msg)
            return "pending_list"
            
    if req_id not in pending and f"approval:{req_id}" not in pending:
        # Fallback if id was not passed cleanly
        return "not_found"
        
    # Attempt claim
    claim_key = f"approval:claim:{req_id}"
    won = await redis_client.setnx(claim_key, approver_name)
    
    if not won:
        winner = await redis_client.get(claim_key)
        winner_name = winner.decode('utf-8') if isinstance(winner, bytes) else winner
        await whatsapp_client.send_message(to=phone, text=f"Richiesta {req_id} già gestita da {winner_name}.")
        return "already_claimed"
        
    # We won the claim. Process the outcome
    req_data_raw = await redis_client.get(f"approval:{req_id}")
    if req_data_raw:
        req_data = json.loads(req_data_raw)
        guest_phone = req_data.get("guest_phone")
        
        cal = _get_calendar_client(config)
        req_type = req_data.get("type", "create")
        
        if req_type == "modify" and cal and "event_id" in req_data and "checkin" in req_data and "checkout" in req_data:
            checkin = date.fromisoformat(req_data["checkin"])
            checkout = date.fromisoformat(req_data["checkout"])
            
            cal.release_range(checkin, checkout)
            
            if action == "OK":
                cal.delete_event(req_data["event_id"])
                # Yellow → Green on the new event (already created at request time)
                new_eid = req_data.get("new_event_id")
                if new_eid:
                    cal.confirm_event(new_eid)
                else:
                    # Backward compat: old requests without new_event_id
                    cal.create_event(
                        checkin_date=checkin,
                        checkout_date=checkout,
                        guest_name=req_data.get("guest_name", "Ospite"),
                        guest_phone=guest_phone,
                        guests_count=req_data.get("guests", 1),
                        total_price=req_data.get("total", 0),
                        language=req_data.get("lang", "it"),
                        payment_state="pending",
                        request_id=req_id
                    )
                if guest_phone:
                    await whatsapp_client.send_message(
                        to=guest_phone,
                        text=f"La tua modifica è stata confermata! Il nuovo totale è €{req_data.get('total', 0)}."
                    )
            else:
                # Reject: remove the pending yellow event for new dates
                new_eid = req_data.get("new_event_id")
                if new_eid:
                    cal.delete_event(new_eid)
                if guest_phone:
                    await whatsapp_client.send_message(
                        to=guest_phone,
                        text="La tua richiesta di modifica non è stata approvata. Il soggiorno originale rimane confermato."
                    )

        if req_type == "create" and cal and "checkin" in req_data and "checkout" in req_data:
            checkin = date.fromisoformat(req_data["checkin"])
            checkout = date.fromisoformat(req_data["checkout"])
            
            cal.release_range(checkin, checkout)
            
            if action == "OK":
                total = req_data.get("total", 0)
                payment_state = "paid"
                payment_mode = config.get("payments", {}).get("mode", "full_on_site")
                
                if config.get("modules", {}).get("payments") and payment_mode != "full_on_site":
                    payment_state = "pending"

                event_id = req_data.get("event_id")
                if event_id:
                    # Yellow → Green (event already created at request time)
                    cal.confirm_event(event_id)
                else:
                    # Backward compat: old requests without event_id
                    event_id = cal.create_event(
                        checkin_date=checkin,
                        checkout_date=checkout,
                        guest_name=req_data.get("guest_name", "Ospite"),
                        guest_phone=guest_phone,
                        guests_count=req_data.get("guests", 1),
                        total_price=total,
                        language=req_data.get("lang", "it"),
                        payment_state=payment_state,
                        request_id=req_id
                    )
                
                if guest_phone:
                    if payment_state == "pending":
                        amount_eur = total
                        if payment_mode == "deposit":
                            pct = config.get("payments", {}).get("deposit_percentage", 50)
                            amount_eur = total * (pct / 100)
                            
                        from modules.payments.stripe_client import StripeClient
                        stripe_client = StripeClient()
                        link = stripe_client.create_payment_link(
                            amount_eur=amount_eur,
                            description=f"Soggiorno B&B - {req_data.get('guest_name', 'Ospite')}",
                            reference=event_id
                        )
                        
                        if payment_mode == "deposit":
                            msg = f"Richiesta confermata! Per bloccare definitivamente le date, è richiesto un anticipo di €{amount_eur:.2f}. Clicca qui per pagare: {link}"
                        else:
                            msg = f"Richiesta confermata! Per completare la prenotazione, effettua il pagamento di €{amount_eur:.2f}. Clicca qui: {link}"
                            
                        await whatsapp_client.send_message(to=guest_phone, text=msg)
                    else:
                        await whatsapp_client.send_message(to=guest_phone, text="Richiesta confermata! Confermata")
            else:
                # Reject: remove the pending yellow event
                event_id = req_data.get("event_id")
                if event_id:
                    cal.delete_event(event_id)
                if guest_phone:
                    await whatsapp_client.send_message(to=guest_phone, text="Purtroppo non possiamo ospitarti per quelle date.")

        if req_type == "cancel" and cal and "event_id" in req_data:
            if action == "OK":
                cal.delete_event(req_data["event_id"])
                
                # Check cancellation policy
                free_days = config.get("booking", {}).get("cancellation_policy", {}).get("free_cancellation_days_before", 0)
                is_free = False
                
                checkin_str = req_data.get("checkin_str")
                if checkin_str:
                    try:
                        import pytz
                        from datetime import datetime, date as date_cls
                        tz = pytz.timezone(config.get("client", {}).get("timezone", "UTC"))
                        today = datetime.now(tz).date()
                        
                        # Parse the custom date string from find_upcoming_events_by_phone
                        # Format is like "Monday January 1, 2026"
                        import re
                        months = {"January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6, "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12}
                        match = re.search(r'([A-Z][a-z]+) (\d+), (\d{4})', checkin_str)
                        if match:
                            month_name, day, year = match.groups()
                            checkin_date = date_cls(int(year), months[month_name], int(day))
                            if (checkin_date - today).days >= free_days:
                                is_free = True
                        else:
                            # Try to parse standard iso format just in case
                            try:
                                checkin_date = date_cls.fromisoformat(checkin_str)
                                if (checkin_date - today).days >= free_days:
                                    is_free = True
                            except ValueError:
                                pass
                    except Exception:
                        pass
                        
                policy_msg = "La cancellazione è gratuita in base ai termini." if is_free else "Verrà applicata la penale di cancellazione come da termini del soggiorno."
                
                if guest_phone:
                    await whatsapp_client.send_message(to=guest_phone, text=f"La tua cancellazione è stata confermata.\n{policy_msg}")
            else:
                if guest_phone:
                    await whatsapp_client.send_message(to=guest_phone, text="La tua richiesta di cancellazione non è stata approvata. Il soggiorno rimane confermato.")


                
    # Notify other approvers
    for approver in config.get("authorized_approvers", []):
        if approver["phone"] != phone:
            await whatsapp_client.send_message(
                to=approver["phone"], 
                text=f"Richiesta {req_id} approvata da {approver_name}." if action == "OK" else f"Richiesta {req_id} rifiutata da {approver_name}."
            )
            
    # Remove from pending
    await redis_client.delete(f"approval:{req_id}")
    
    return "approved" if action == "OK" else "rejected"
