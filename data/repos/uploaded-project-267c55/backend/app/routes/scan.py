"""
Package scanning routes (Phase 8). See models/scan.py's module
docstring for the "delivery id IS the package code" design, and
services/scanning.py for QR generation + duplicate-scan protection.

Authorization mirrors routes/pod.py's shape exactly (same reasoning
applies: an agent may only scan/view their own assigned deliveries;
any dispatcher/admin in the org may scan/view any of the org's
deliveries), since this is the same "an agent's own work vs. a
dispatcher coordinating across everyone" pattern.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, date

from app.db.session import get_db
from app.models.delivery import DeliveryRecordDB
from app.models.scan import PackageScanDB, ScanIn, ScanOut, ScannedPackageOut, ScanType
from app.models.user import UserDB, UserRole
from app.services.permissions import require_permission
from app.services.scanning import generate_package_qr_svg, is_duplicate_scan
from app.routes.auth import get_current_user

router = APIRouter(tags=["scanning"])


def _get_delivery_or_404(db: Session, delivery_id: str, org_id: str) -> DeliveryRecordDB:
    delivery = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == delivery_id, DeliveryRecordDB.org_id == org_id,
    ).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Invalid scan: no package found for this code.")
    return delivery


def _require_scan_access(delivery: DeliveryRecordDB, current_user: UserDB) -> None:
    if current_user.role == UserRole.agent and delivery.agent_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only scan your own assigned deliveries.")


@router.get("/deliveries/{delivery_id}/package-qr")
def get_package_qr(delivery_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    delivery = _get_delivery_or_404(db, delivery_id, current_user.org_id)
    _require_scan_access(delivery, current_user)
    svg = generate_package_qr_svg(delivery.id)
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/scan/{code}", response_model=ScannedPackageOut)
def resolve_scanned_code(code: str, db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    """
    What the scanning UI calls the moment a QR/barcode is read, BEFORE
    committing to a specific scan stage — resolves the code to a real
    delivery (org-scoped, so a code from another organization's package
    correctly comes back as invalid) so the agent can confirm what they
    just scanned and then pick which stage to record.
    """
    delivery = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.id == code, DeliveryRecordDB.org_id == current_user.org_id,
    ).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Invalid scan: no package found for this code.")
    if current_user.role == UserRole.agent and delivery.agent_id != current_user.id:
        raise HTTPException(status_code=403, detail="This package isn't assigned to you.")
    return ScannedPackageOut(delivery_id=delivery.id, order_id=delivery.order_id, status=delivery.status.value, agent_id=delivery.agent_id)


@router.post("/deliveries/{delivery_id}/scan", response_model=ScanOut)
def record_scan(
    delivery_id: str,
    payload: ScanIn,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    delivery = _get_delivery_or_404(db, delivery_id, current_user.org_id)
    _require_scan_access(delivery, current_user)

    scanned_at = payload.scanned_at or datetime.utcnow()
    if is_duplicate_scan(db, delivery_id, payload.scan_type, scanned_at):
        raise HTTPException(status_code=400, detail="This exact scan was just recorded — treating it as a duplicate.")

    scan = PackageScanDB(
        org_id=current_user.org_id,
        delivery_id=delivery_id,
        scan_type=payload.scan_type,
        scanned_by_user_id=current_user.id,
        location_note=payload.location_note,
        scanned_at=scanned_at,
        captured_offline=payload.captured_offline,
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan


@router.get("/deliveries/{delivery_id}/scans", response_model=List[ScanOut])
def get_scan_history(delivery_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    delivery = _get_delivery_or_404(db, delivery_id, current_user.org_id)
    _require_scan_access(delivery, current_user)
    return db.query(PackageScanDB).filter(
        PackageScanDB.delivery_id == delivery_id,
    ).order_by(PackageScanDB.scanned_at.asc()).all()


@router.get("/admin/scans", response_model=List[ScanOut])
def list_org_scans(
    scan_type: Optional[ScanType] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_permission("deliveries.view")),
):
    query = db.query(PackageScanDB).filter(PackageScanDB.org_id == current_user.org_id)
    if scan_type:
        query = query.filter(PackageScanDB.scan_type == scan_type)
    if date_from:
        query = query.filter(PackageScanDB.scanned_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.filter(PackageScanDB.scanned_at <= datetime.combine(date_to, datetime.max.time()))
    return query.order_by(PackageScanDB.scanned_at.desc()).all()
