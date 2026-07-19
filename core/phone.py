import re


def normalize_phone(phone: str) -> str:
    """
    Normalize phone numbers for WhatsApp API.
    """
    if not phone:
        return phone

    phone = phone.strip()
    
    # Se inizia con "+" lo teniamo
    has_plus = phone.startswith("+")
    if has_plus:
        phone = phone[1:]
        
    # Se è un cellulare italiano (inizia con 3 ed è lungo 9/10 cifre)
    if phone.startswith("3") and len(phone) in (9, 10):
        phone = "39" + phone

    # Argentina quirk (old)
    if re.match(r'^549\d{10}$', phone):
        phone = '54' + phone[3:]

    # Ripristiniamo il formato col plus solo se ci serve (o come stringa liscia per WA)
    # WA accetta numeri puliti senza +
    return phone
