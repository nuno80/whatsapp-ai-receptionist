import re


def normalize_phone(phone: str) -> str:
    """
    Normalize phone numbers for WhatsApp API.
    Forces IT country code (39) for numbers starting with '3' without country code.
    """
    if not phone:
        return phone

    phone = re.sub(r"[^\d+]", "", phone.strip())
    
    if phone.startswith("+"):
        phone = phone[1:]
        
    if phone.startswith("00"):
        phone = phone[2:]
        
    # Se è un cellulare italiano (inizia con 3 ed è lungo 9/10 cifre)
    if phone.startswith("3") and len(phone) in (9, 10):
        phone = "39" + phone

    return phone
