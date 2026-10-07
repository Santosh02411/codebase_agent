"""
Templated customer notifications (Phase 10). See
models/notification_template.py's module docstring for the overall
design — this is the one function that actually sends one, consulting
an org's customization if it exists and falling back to the built-in
default otherwise.
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.models.notification_template import NotificationTemplateDB, DEFAULT_TEMPLATES
from app.models.customer_notification import CustomerNotificationDB
from app.services.email import _send_email
from app.services.sms import send_free_text_sms, send_free_text_whatsapp


def get_effective_template(db: Session, org_id: str, event_type: str) -> dict:
    """The template that will actually be used for this org/event — either their customization or the built-in default. Same shape either way, so callers never need to branch on which."""
    custom = db.query(NotificationTemplateDB).filter(
        NotificationTemplateDB.org_id == org_id, NotificationTemplateDB.event_type == event_type,
    ).first()
    if custom:
        return {
            "subject": custom.subject, "body": custom.body,
            "email_enabled": custom.email_enabled, "sms_enabled": custom.sms_enabled,
            "whatsapp_enabled": custom.whatsapp_enabled, "is_default": False,
        }
    subject, body = DEFAULT_TEMPLATES[event_type]
    return {"subject": subject, "body": body, "email_enabled": True, "sms_enabled": False, "whatsapp_enabled": False, "is_default": True}


def send_templated_notification(
    db: Session, org_id: str, event_type: str, order_id: str,
    customer_id: Optional[str], customer_email: Optional[str], customer_phone: Optional[str],
    delivery_id: Optional[str] = None,
) -> None:
    """
    Sends a notification for one of Phase 10's new event types (see
    models/notification_template.py's EVENT_TYPES) through whichever
    channels the effective template has enabled, using this org's
    customized wording if they've set one. In-app notification always
    fires when there's a customer_id, same as
    notify_customer_of_status_change's "primary channel" — email/SMS/
    WhatsApp are the configurable secondary channels here.
    Best-effort throughout: a failure on any one channel never blocks
    the others or raises to the caller. `delivery_id` is optional
    (e.g. a subscription reminder fires before any order/delivery
    exists yet) — CustomerNotificationDB.delivery_id is NOT NULL, so
    an empty string is stored rather than a real id when there isn't
    one; the in-app notification list only ever needs order_id/message
    to render, so this doesn't lose anything the UI actually uses.
    """
    template = get_effective_template(db, org_id, event_type)
    message = template["body"].format(order_id=order_id)

    if customer_id:
        try:
            db.add(CustomerNotificationDB(customer_id=customer_id, delivery_id=delivery_id or "", order_id=order_id, message=message))
            db.commit()
        except Exception as error:  # noqa: BLE001
            print(f"In-app templated notification failed for {order_id}: {error}")

    if template["email_enabled"] and customer_email:
        try:
            _send_email(customer_email, template["subject"], message)
        except Exception as error:  # noqa: BLE001
            print(f"Email templated notification failed for {order_id}: {error}")

    if template["sms_enabled"] and customer_phone:
        try:
            send_free_text_sms(customer_phone, message)
        except Exception as error:  # noqa: BLE001
            print(f"SMS templated notification failed for {order_id}: {error}")

    if template["whatsapp_enabled"] and customer_phone:
        try:
            send_free_text_whatsapp(customer_phone, message)
        except Exception as error:  # noqa: BLE001
            print(f"WhatsApp templated notification failed for {order_id}: {error}")
