import os
import json
import hmac
import hashlib
import stripe
import logging

logger = logging.getLogger(__name__)

def validate_stripe_signature(payload: bytes, sig_header: str, secret: str) -> bool:
    try:
        stripe.WebhookSignature.verify_header(payload, sig_header, secret)
        return True
    except stripe.error.SignatureVerificationError:
        return False

class StripeClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("STRIPE_API_KEY", "")
        stripe.api_key = self.api_key

    def create_payment_link(self, amount_eur: float, description: str, reference: str) -> str:
        """Create a one-time Stripe checkout session and return the URL."""
        if not self.api_key:
            logger.warning("No Stripe API key, returning dummy URL")
            return "https://checkout.stripe.com/dummy"
            
        try:
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'eur',
                        'product_data': {
                            'name': description,
                        },
                        'unit_amount': int(amount_eur * 100), # amount in cents
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url='https://example.com/success',
                cancel_url='https://example.com/cancel',
                client_reference_id=reference,
            )
            return session.url
        except Exception as e:
            logger.error("Failed to create Stripe session: %s", e)
            return ""