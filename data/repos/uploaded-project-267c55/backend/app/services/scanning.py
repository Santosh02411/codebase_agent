"""
Package scanning business logic (Phase 8): QR generation and
duplicate-scan protection. Recording an actual scan (the DB write) is
simple enough it stays in routes/scan.py directly — this module is for
the two things worth pulling out and unit-testing on their own.
"""

import io
from datetime import datetime, timedelta

import qrcode
import qrcode.image.svg
from sqlalchemy.orm import Session

from app.models.scan import PackageScanDB, ScanType

# A repeat scan of the SAME stage for the SAME package within this
# window is treated as a duplicate (an agent's scanner double-firing,
# or a habit of scanning twice to "make sure") and rejected rather than
# logged twice. Anything past this window is a legitimate new event —
# e.g. a package genuinely passing through the same hub stage again on
# a re-route — so it's accepted normally.
DUPLICATE_SCAN_WINDOW_SECONDS = 60


def generate_package_qr_svg(delivery_id: str) -> str:
    """Returns raw SVG markup encoding the delivery's id — see models/scan.py's module docstring for why the delivery id itself is the package code."""
    factory = qrcode.image.svg.SvgPathImage
    img = qrcode.make(delivery_id, image_factory=factory)
    buffer = io.BytesIO()
    img.save(buffer)
    return buffer.getvalue().decode("utf-8")


def is_duplicate_scan(db: Session, delivery_id: str, scan_type: ScanType, at: datetime) -> bool:
    cutoff = at - timedelta(seconds=DUPLICATE_SCAN_WINDOW_SECONDS)
    return db.query(PackageScanDB.id).filter(
        PackageScanDB.delivery_id == delivery_id,
        PackageScanDB.scan_type == scan_type,
        PackageScanDB.scanned_at >= cutoff,
        PackageScanDB.scanned_at <= at,
    ).first() is not None
