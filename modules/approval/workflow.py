import json
import random
import string
import redis.asyncio as redis

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
    # For now, simplistic
    req_data_raw = await redis_client.get(f"approval:{req_id}")
    if req_data_raw:
        req_data = json.loads(req_data_raw)
        guest_phone = req_data.get("guest_phone")
        if guest_phone:
            if action == "OK":
                await whatsapp_client.send_message(to=guest_phone, text="Richiesta confermata!")
            else:
                await whatsapp_client.send_message(to=guest_phone, text="Richiesta rifiutata.")
                
    # Notify other approvers
    for approver in config.get("authorized_approvers", []):
        if approver["phone"] != phone:
            await whatsapp_client.send_message(
                to=approver["phone"], 
                text=f"Richiesta {req_id} gestita da {approver_name}."
            )
            
    # Remove from pending
    await redis_client.delete(f"approval:{req_id}")
    
    return "approved" if action == "OK" else "rejected"
