"""
Proof of Delivery routes (Phase 1).

Three groups of endpoints:
  - /deliveries/{id}/pod/*      agent/dispatcher capture + view for one delivery
  - /admin/pod-settings         admin-configurable org requirements
  - /admin/pod-report           CSV export

Authorization story, consistently applied:
  - Only the ASSIGNED agent (or any dispatcher/admin in the org) may
    generate an OTP or submit a POD for a delivery.
  - Any dispatcher/admin in the org may view any of the org's PODs.
  - The assigned agent may view POD for their own deliveries.
  - A customer may only view POD for a delivery on THEIR OWN order —
    see the separate customer-scoped endpoint in customer_dashboard.py.
Every query is additionally scoped by org_id, taken from the
authenticated user, never from client input.
"""

import csv
import io
from datetime import datetime, date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.models.delivery import DeliveryRecordDB
from app.models.organization import OrganizationDB
from app.models.user import UserDB, UserRole
from app.models.proof_of_delivery import (
    ProofOfDeliveryDB,
    ProofOfDeliverySubmit,
    ProofOfDeliveryOut,
    DeliveryOtpGenerateOut,
    PodSettingsOut,
    PodSettingsUpdate,
)
from app.routes.auth import get_current_user
from app.routes.admin import require_admin
from app.routes.deliveries import require_dispatcher
from app.services.pod import (
    generate_and_send_delivery_otp,
    verify_delivery_otp,
    missing_pod_requirements,
)
from app.services.action_log import record_action
from app.services.history import record_history_entry

router = APIRouter(tags=["proof-of-delivery"])


def _get_delivery_or_404(db: Session, delivery_id: str, org_id: str) -> DeliveryRecordDB:
    delivery = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == delivery_id,
        DeliveryRecordDB.org_id == org_id,
    ).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery record not found")
    return delivery


def _require_capture_access(delivery: DeliveryRecordDB, current_user: UserDB) -> None:
    """Assigned agent, or any dispatcher/admin in the org — not any agent."""
    if current_user.role == UserRole.agent and delivery.agent_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only capture proof of delivery for your own assigned deliveries.")


# ---------- Capture (agent-facing) ----------

@router.post("/deliveries/{delivery_id}/pod/otp", response_model=DeliveryOtpGenerateOut)
def generate_delivery_otp(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    delivery = _get_delivery_or_404(db, delivery_id, current_user.org_id)
    _require_capture_access(delivery, current_user)

    channel, hint = generate_and_send_delivery_otp(db, delivery)
    return DeliveryOtpGenerateOut(sent=channel != "none", channel=channel, destination_hint=hint)


@router.post("/deliveries/{delivery_id}/pod", response_model=ProofOfDeliveryOut)
def submit_proof_of_delivery(
    delivery_id: str,
    payload: ProofOfDeliverySubmit,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """
    Captures proof of delivery for this delivery. Does NOT itself change
    the delivery's status — the agent still calls PATCH
    /deliveries/{id} with status=delivered as before; that endpoint
    checks for an existing POD row (via services/pod.py) when the org
    requires one. Submitting POD ahead of that call is what makes the
    status update succeed.

    Can be called more than once for the same delivery (e.g. a
    dispatcher asks for a redo) — each call creates a new POD row, and
    GET .../pod/history returns all of them; GET .../pod returns the
    latest.
    """
    delivery = _get_delivery_or_404(db, delivery_id, current_user.org_id)
    _require_capture_access(delivery, current_user)

    org = db.query(OrganizationDB).filter(OrganizationDB.id == current_user.org_id).first()

    otp_ok = False
    if payload.otp_code:
        otp_ok = verify_delivery_otp(db, delivery_id, current_user.org_id, payload.otp_code)
        if not otp_ok:
            raise HTTPException(status_code=400, detail="That verification code is incorrect or has expired.")
    elif org.pod_require_otp:
        raise HTTPException(status_code=400, detail="A verification code from the recipient is required.")

    missing = missing_pod_requirements(org, payload, otp_ok)
    if missing:
        raise HTTPException(status_code=400, detail=" ".join(missing))

    pod = ProofOfDeliveryDB(
        delivery_id=delivery_id,
        org_id=current_user.org_id,
        agent_id=delivery.agent_id or current_user.id,
        recipient_name=(payload.recipient_name or "").strip() or None,
        recipient_phone=(payload.recipient_phone or "").strip() or None,
        otp_verified=otp_ok,
        signature_data_url=payload.signature_data_url,
        photo_data_url=payload.photo_data_url,
        latitude=payload.latitude,
        longitude=payload.longitude,
        notes=payload.notes,
        captured_at=payload.captured_at or datetime.utcnow(),
        captured_offline=payload.captured_offline,
    )
    db.add(pod)
    db.commit()
    db.refresh(pod)

    record_history_entry(
        db,
        delivery_id=delivery_id,
        changed_by_user_id=current_user.id,
        changed_by_display_name=current_user.display_name,
        old_status=delivery.status,
        new_status=delivery.status,
        changed_at=pod.captured_at,
        note="Proof of delivery captured" + (" (offline capture, synced later)" if payload.captured_offline else ""),
    )

    return pod


@router.get("/deliveries/{delivery_id}/pod", response_model=ProofOfDeliveryOut)
def get_latest_pod(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    delivery = _get_delivery_or_404(db, delivery_id, current_user.org_id)
    if current_user.role == UserRole.agent and delivery.agent_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only view proof of delivery for your own assigned deliveries.")

    pod = db.query(ProofOfDeliveryDB).filter(
        ProofOfDeliveryDB.delivery_id == delivery_id,
        ProofOfDeliveryDB.org_id == current_user.org_id,
    ).order_by(ProofOfDeliveryDB.captured_at.desc()).first()
    if not pod:
        raise HTTPException(status_code=404, detail="No proof of delivery has been captured for this delivery yet.")
    return pod


@router.get("/deliveries/{delivery_id}/pod/history", response_model=List[ProofOfDeliveryOut])
def get_pod_history(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    delivery = _get_delivery_or_404(db, delivery_id, current_user.org_id)
    if current_user.role == UserRole.agent and delivery.agent_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only view proof of delivery for your own assigned deliveries.")

    return db.query(ProofOfDeliveryDB).filter(
        ProofOfDeliveryDB.delivery_id == delivery_id,
        ProofOfDeliveryDB.org_id == current_user.org_id,
    ).order_by(ProofOfDeliveryDB.captured_at.desc()).all()


# ---------- Org settings (admin-facing) ----------

@router.get("/admin/pod-settings", response_model=PodSettingsOut)
def get_pod_settings(db: Session = Depends(get_db), current_user: UserDB = Depends(require_admin)):
    org = db.query(OrganizationDB).filter(OrganizationDB.id == current_user.org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


@router.patch("/admin/pod-settings", response_model=PodSettingsOut)
def update_pod_settings(
    payload: PodSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_admin),
):
    org = db.query(OrganizationDB).filter(OrganizationDB.id == current_user.org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    before = {
        "pod_require_recipient_name": org.pod_require_recipient_name,
        "pod_require_signature_or_photo": org.pod_require_signature_or_photo,
        "pod_require_otp": org.pod_require_otp,
        "pod_require_gps": org.pod_require_gps,
    }
    org.pod_require_recipient_name = payload.pod_require_recipient_name
    org.pod_require_signature_or_photo = payload.pod_require_signature_or_photo
    org.pod_require_otp = payload.pod_require_otp
    org.pod_require_gps = payload.pod_require_gps
    db.commit()
    db.refresh(org)

    record_action(
        db, org_id=current_user.org_id, actor_user_id=current_user.id,
        actor_display_name=current_user.display_name, action="update",
        entity_type="pod_settings", summary="Updated proof-of-delivery requirements.",
        before=before, after=payload.dict(),
    )
    return org


# ---------- Report (dispatcher/admin-facing) ----------

@router.get("/admin/pod-report")
def export_pod_report_csv(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher),
):
    """Downloadable CSV of every POD captured for the org, optionally date-filtered — same shape/tooling as routes/export.py."""
    query = db.query(ProofOfDeliveryDB).filter(ProofOfDeliveryDB.org_id == current_user.org_id)
    if date_from:
        query = query.filter(ProofOfDeliveryDB.captured_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.filter(ProofOfDeliveryDB.captured_at <= datetime.combine(date_to, datetime.max.time()))
    pods = query.order_by(ProofOfDeliveryDB.captured_at.desc()).all()

    delivery_ids = {p.delivery_id for p in pods}
    deliveries = db.query(DeliveryRecordDB).filter(DeliveryRecordDB.id.in_(delivery_ids)).all() if delivery_ids else []
    order_id_by_delivery = {d.id: d.order_id for d in deliveries}

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "order_id", "delivery_id", "agent_id", "recipient_name", "recipient_phone",
        "otp_verified", "has_signature", "has_photo", "latitude", "longitude",
        "notes", "captured_offline", "captured_at",
    ])
    for p in pods:
        writer.writerow([
            order_id_by_delivery.get(p.delivery_id, ""), p.delivery_id, p.agent_id or "",
            p.recipient_name or "", p.recipient_phone or "", p.otp_verified,
            bool(p.signature_data_url), bool(p.photo_data_url),
            p.latitude or "", p.longitude or "", p.notes or "",
            p.captured_offline, p.captured_at.isoformat(),
        ])
    buffer.seek(0)
    return StreamingResponse(
        buffer, media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=proof_of_delivery_report.csv"},
    )
