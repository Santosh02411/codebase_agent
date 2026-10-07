"""
Real payment gateway integration via Razorpay — chosen because it's the
standard, free-to-test option for an India-based project (supports INR,
UPI, cards, netbanking) and its test mode needs no real bank account or
KYC to fully exercise.

To make this genuinely real:
    1. Sign up free at dashboard.razorpay.com (takes ~5 minutes, no KYC
       needed for Test Mode)
    2. Settings -> API Keys -> Generate Test Key
    3. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET below / in your .env
Once set, checkout genuinely creates a real order with Razorpay's API,
opens their real Checkout.js widget in the browser, and this backend
verifies the payment's HMAC signature exactly the way Razorpay's own
docs specify — no shortcuts. Use their published test card
4111 1111 1111 1111 (any future expiry/CVV) to pay for real through
their sandbox.

WITHOUT keys configured, checkout still fully works end-to-end — cart,
address, order creation, a Delivery being generated, notifications
firing — but the payment step itself is simulated locally instead of
touching Razorpay's servers, so the whole feature can be evaluated
without forcing a signup first. This is NEVER silently passed off as a
real payment: every order created this way is flagged
is_test_mode_payment=True in the database, and the frontend visibly
labels it "TEST MODE — no payment gateway connected" wherever it's shown.
"""

import hashlib
import hmac
import os

RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")

IS_CONFIGURED = bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)


def create_razorpay_order(amount_paise: int, receipt: str) -> dict:
    """
    Creates a real order with Razorpay's API. Only called when
    IS_CONFIGURED is True. Returns Razorpay's order object, which
    includes the `id` the frontend's Checkout.js widget needs.
    """
    import razorpay
    client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    return client.order.create({
        "amount": amount_paise,  # Razorpay works in the smallest currency unit (paise for INR)
        "currency": "INR",
        "receipt": receipt,
        "payment_capture": 1,
    })


def create_razorpay_refund(payment_id: str, amount_paise: int) -> dict:
    """
    Issues a real refund against a captured Razorpay payment — the
    actual API call that moves money back to the customer. Only called
    when IS_CONFIGURED is True and the order being cancelled was a real
    (non test-mode) payment; see services/refund.py for the caller.
    """
    import razorpay
    client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    return client.payment.refund(payment_id, {"amount": amount_paise})


def verify_razorpay_signature(razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str) -> bool:
    """
    Verifies a completed payment is genuinely authorized by Razorpay and
    hasn't been tampered with client-side — the exact HMAC-SHA256 check
    Razorpay's own documentation specifies. NEVER trust a "payment
    succeeded" claim from the browser alone; this signature is the proof.
    """
    if not RAZORPAY_KEY_SECRET:
        return False

    payload = f"{razorpay_order_id}|{razorpay_payment_id}"
    expected_signature = hmac.new(
        RAZORPAY_KEY_SECRET.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_signature, razorpay_signature or "")
