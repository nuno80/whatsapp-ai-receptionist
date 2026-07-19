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
        f"Nuova richiesta {req_id}:\n"
        f"Da: {data.get('guest_name')} ({data.get('guest_phone')})\n"
        f"Date: {data.get('dates')}\n"
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
        if cal and "checkin" in req_data and "checkout" in req_data:
            checkin = date.fromisoformat(req_data["checkin"])
            checkout = date.fromisoformat(req_data["checkout"])
            
            cal.release_range(checkin, checkout)
            
            if action == "OK":
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
            if action == "OK":
                await whatsapp_client.send_message(to=guest_phone, text="Richiesta confermata! Confermata")
            else:
                await whatsapp_client.send_message(to=guest_phone, text="Purtroppo non possiamo ospitarti per quelle date.")
                
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
