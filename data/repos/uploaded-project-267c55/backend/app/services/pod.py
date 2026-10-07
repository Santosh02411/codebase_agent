"""
Proof-of-delivery business logic: generating/verifying the recipient
OTP, and checking a submitted POD against the organization's
configured requirements. Kept separate from routes/pod.py the same way
services/coupons.py is kept separate from routes/coupons.py — so the
actual rules are unit-testable and reusable without an HTTP round trip.
"""

import random
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.delivery import DeliveryRecordDB
from app.models.organization import OrganizationDB
from app.models.proof_of_delivery import DeliveryOtpDB, ProofOfDeliverySubmit, DELIVERY_OTP_EXPIRY_MINUTES
from app.services.auth import hash_password, verify_password
from app.services.email import _send_email
from app.services.sms import send_status_notification_sms


def _generate_numeric_code() -> str:
    return f"{random.randint(0, 999999):06d}"


def _mask_contact(value: str) -> str:
    """Same masking spirit as models/email_otp.py's mask_email(), generalized to phone too."""
    if "@" in value:
        local, _, domain = value.partition("@")
        masked_local = local[0] + "*" * max(len(local) - 1, 1) if len(local) <= 2 else local[0] + "*" * (len(local) - 2) + local[-1]
        return f"{masked_local}@{domain}"
    # phone-ish: keep last 3 digits visible
    digits = value.strip()
    if len(digits) <= 3:
        return "*" * len(digits)
    return "*" * (len(digits) - 3) + digits[-3:]


def generate_and_send_delivery_otp(db: Session, delivery: DeliveryRecordDB):
    """
    Creates a new hashed OTP for this delivery and best-effort sends it
    to whichever contact info the delivery has on file (email preferred,
    then SMS) — mirroring notify_customer_of_status_change's channel
    fallback in services/notifications.py. Any previous unused code for
    this delivery is left alone; only the most recently *used* one
    counts, and verify_delivery_otp only ever accepts the newest valid
    code (see below), so an old unused code simply expires unused.

    Returns (channel, destination_hint) — never the plaintext code
    itself, same reasoning as the email/2FA OTP flow.
    """
    code = _generate_numeric_code()
    otp = DeliveryOtpDB(
        delivery_id=delivery.id,
        org_id=delivery.org_id,
        code_hash=hash_password(code),
        channel="none",
    )

    if delivery.customer_email:
        otp.channel = "email"
        db.add(otp)
        db.commit()
        try:
            _send_email(
                delivery.customer_email,
                "Your delivery verification code",
                f"Your delivery verification code for order {delivery.order_id} is: {code}\n"
                f"Share this with the delivery agent only once your order is in hand.\n"
                f"This code expires in {DELIVERY_OTP_EXPIRY_MINUTES} minutes.",
            )
        except Exception:
            pass  # best-effort, same tolerance as every other notification send in this project
        return "email", _mask_contact(delivery.customer_email)

    if delivery.customer_phone:
        otp.channel = "sms"
        db.add(otp)
        db.commit()
        try:
            send_status_notification_sms(
                delivery.customer_phone, delivery.order_id,
                f"Your delivery verification code is {code}", tracking_link="",
            )
        except Exception:
            pass
        return "sms", _mask_contact(delivery.customer_phone)

    # No contact info on file at all — still create the row (so a
    # dispatcher/agent calling GET can see "no code sent") but there's
    # nowhere to send it. The org's pod_require_otp requirement, if on,
    # will then correctly block this delivery from being marked
    # delivered until the dispatcher adds contact info or turns the
    # requirement off for this org — it never silently no-ops.
    db.add(otp)
    db.commit()
    return "none", None


def verify_delivery_otp(db: Session, delivery_id: str, org_id: str, code: str) -> bool:
    """
    Checks `code` against the most recently generated, unexpired,
    unused OTP for this delivery. Marks it used on success (single-use).
    Returns False (never raises) for a wrong/missing/expired code —
    callers decide what HTTP error that becomes.
    """
    if not code:
        return False
    otp = db.query(DeliveryOtpDB).filter(
        DeliveryOtpDB.delivery_id == delivery_id,
        DeliveryOtpDB.org_id == org_id,
        DeliveryOtpDB.used == False,  # noqa: E712
    ).order_by(DeliveryOtpDB.created_at.desc()).first()

    if not otp or otp.expires_at < datetime.utcnow():
        return False
    if not verify_password(code.strip(), otp.code_hash):
        return False

    otp.used = True
    db.commit()
    return True


def missing_pod_requirements(org: OrganizationDB, payload: ProofOfDeliverySubmit, otp_ok: bool) -> list[str]:
    missing = []
    if org.pod_require_recipient_name and not (payload.recipient_name or "").strip():
        missing.append("Recipient name is required.")
    if org.pod_require_signature_or_photo and not (payload.signature_data_url or payload.photo_data_url):
        missing.append("A signature or photo is required.")
    if org.pod_require_otp and not otp_ok:
        missing.append("Recipient OTP verification is required.")
    if org.pod_require_gps and not (payload.latitude and payload.longitude):
        missing.append("GPS location is required.")
    return missing


def org_requires_any_pod(org: OrganizationDB) -> bool:
    return bool(
        org.pod_require_recipient_name
        or org.pod_require_signature_or_photo
        or org.pod_require_otp
        or org.pod_require_gps
    )


def pod_exists_for_delivery(db: Session, delivery_id: str, org_id: str) -> bool:
    """
    Whether at least one POD row has been captured for this delivery —
    used by the enforcement check at BOTH places a delivery can be
    marked delivered: the online PATCH (routes/deliveries.py) and the
    offline-sync path (services/conflict_resolver.py). Import is local
    to avoid a circular import (proof_of_delivery model has no
    dependency back on this module, but keeping the import next to its
    one use here mirrors how the rest of this file already imports
    narrowly).
    """
    from app.models.proof_of_delivery import ProofOfDeliveryDB
    return db.query(ProofOfDeliveryDB.id).filter(
        ProofOfDeliveryDB.delivery_id == delivery_id,
        ProofOfDeliveryDB.org_id == org_id,
    ).first() is not None
