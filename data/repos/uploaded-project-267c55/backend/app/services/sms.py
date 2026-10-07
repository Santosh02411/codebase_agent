"""
SMS sending, abstracted the same way as services/email.py: by default,
"sending" an SMS just prints it clearly to the backend console/log
instead of actually delivering it — zero cost, no account needed, and
enough to fully develop/test the notification flow.

If TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER are all
set in the environment, this switches to actually sending via Twilio
(the most common SMS provider — has a free trial with real credit, so
this can be tested with a real phone at zero cost too, within trial
limits). Nothing about the calling code changes based on which path is
used; only this module's internal behavior does.
"""

import os

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER")


def send_free_text_sms(to_phone: str, message: str) -> None:
    """
    Generic-text counterpart to send_status_notification_sms (Phase 10)
    — used by services/notification_templates.py's send_templated_notification()
    where the message is a template body, not a fixed "order is now X"
    sentence. Same provider logic/fallback exactly, just without baking
    in that specific wording.
    """
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER):
        print("=" * 60)
        print("SMS (no Twilio credentials configured — printed instead of sent)")
        print(f"To: {to_phone}")
        print(message)
        print("=" * 60)
        return

    try:
        from twilio.rest import Client
    except ImportError:
        print("Twilio credentials are set but the 'twilio' package isn't installed. Run: pip install twilio")
        return

    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    client.messages.create(body=message, from_=TWILIO_FROM_NUMBER, to=to_phone)


def send_status_notification_sms(to_phone: str, order_id: str, status_label: str, tracking_link: str) -> None:
    message = f"Delivery Sync: order {order_id} is now {status_label}. Track: {tracking_link}"

    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER):
        # No Twilio configured — this is the default, zero-cost path.
        print("=" * 60)
        print("SMS (no Twilio credentials configured — printed instead of sent)")
        print(f"To: {to_phone}")
        print(message)
        print("=" * 60)
        return

    # Twilio is configured — actually send a real SMS. Imported here
    # (not at module top) so the `twilio` package is only required at
    # all if someone actually configures real credentials — the default,
    # zero-cost console path works with zero extra dependencies installed.
    try:
        from twilio.rest import Client
    except ImportError:
        print(
            "Twilio credentials are set but the 'twilio' package isn't installed. "
            "Run: pip install twilio"
        )
        return

    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    client.messages.create(body=message, from_=TWILIO_FROM_NUMBER, to=to_phone)


# Twilio's WhatsApp Sandbox is free with the same trial account used for
# SMS above — no separate signup, no WhatsApp Business API approval
# needed for development/demo use. TWILIO_WHATSAPP_FROM is Twilio's
# sandbox number, formatted as 'whatsapp:+14155238886' (their standard
# sandbox number — see twilio.com/console/sms/whatsapp/sandbox). A real
# production WhatsApp number requires Meta business verification, which
# is genuinely out of reach for a project at this stage — the sandbox is
# the honest, fully-real alternative available without that.
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM")


def send_free_text_whatsapp(to_phone: str, message: str) -> None:
    """Generic-text counterpart to send_status_notification_whatsapp (Phase 10) — see send_free_text_sms's docstring above for the same reasoning."""
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM):
        print("=" * 60)
        print("WHATSAPP (no Twilio WhatsApp sandbox configured — printed instead of sent)")
        print(f"To: {to_phone}")
        print(message)
        print("=" * 60)
        return

    try:
        from twilio.rest import Client
    except ImportError:
        print("Twilio credentials are set but the 'twilio' package isn't installed. Run: pip install twilio")
        return

    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    to_whatsapp = to_phone if to_phone.startswith("whatsapp:") else f"whatsapp:{to_phone}"
    client.messages.create(body=message, from_=TWILIO_WHATSAPP_FROM, to=to_whatsapp)


def send_status_notification_whatsapp(to_phone: str, order_id: str, status_label: str, tracking_link: str) -> None:
    message = f"Delivery Sync: order {order_id} is now *{status_label}*. Track: {tracking_link}"

    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM):
        print("=" * 60)
        print("WHATSAPP (no Twilio WhatsApp sandbox configured — printed instead of sent)")
        print(f"To: {to_phone}")
        print(message)
        print("=" * 60)
        return

    try:
        from twilio.rest import Client
    except ImportError:
        print("Twilio credentials are set but the 'twilio' package isn't installed. Run: pip install twilio")
        return

    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    to_whatsapp = to_phone if to_phone.startswith("whatsapp:") else f"whatsapp:{to_phone}"
    client.messages.create(body=message, from_=TWILIO_WHATSAPP_FROM, to=to_whatsapp)
