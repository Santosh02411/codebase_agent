"""
Analytics/reporting export — lets a dispatcher/admin download their
organization's delivery data as a CSV for a given date range, for use in
spreadsheets, external reporting tools, etc.

Built with Python's built-in `csv` module writing into an in-memory
buffer, rather than hand-building comma-separated strings — this
guarantees correct escaping/quoting of any field that happens to contain
a comma or quote (notes, in particular), the same category of bug the
bulk-import CSV parser was specifically built to avoid on the way in.
"""

import csv
import io
from datetime import datetime, date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.delivery import DeliveryRecordDB
from app.models.user import UserDB
from app.routes.deliveries import require_dispatcher

router = APIRouter(prefix="/deliveries", tags=["export"])


@router.get("/export")
def export_deliveries_csv(
    date_from: date | None = Query(None, description="Include deliveries updated on/after this date"),
    date_to: date | None = Query(None, description="Include deliveries updated on/before this date"),
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher),
):
    """
    Streams a CSV of the caller's organization's deliveries, optionally
    filtered to a date range (matched against `updated_at`). Dispatcher/
    admin-only, and scoped to the caller's own organization — same
    isolation guarantee as every other endpoint in this app.
    """
    query = db.query(DeliveryRecordDB).filter(DeliveryRecordDB.org_id == current_user.org_id)

    if date_from:
        query = query.filter(DeliveryRecordDB.updated_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.filter(DeliveryRecordDB.updated_at <= datetime.combine(date_to, datetime.max.time()))

    deliveries = query.order_by(DeliveryRecordDB.updated_at.desc()).all()

    # Look up agent display names once, rather than one query per row
    agent_ids = {d.agent_id for d in deliveries}
    agents = db.query(UserDB).filter(UserDB.id.in_(agent_ids)).all() if agent_ids else []
    agent_name_by_id = {a.id: a.display_name for a in agents}

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "order_id", "agent", "status", "zone", "expected_by",
        "notes", "location_note", "created_at", "updated_at",
    ])
    for d in deliveries:
        writer.writerow([
            d.order_id,
            agent_name_by_id.get(d.agent_id, d.agent_id),
            d.status.value,
            d.zone or "",
            d.expected_by.isoformat() if d.expected_by else "",
            d.notes or "",
            d.location_note or "",
            d.created_at.isoformat(),
            d.updated_at.isoformat(),
        ])

    buffer.seek(0)
    filename = f"deliveries_export_{date.today().isoformat()}.csv"
    return StreamingResponse(
        buffer,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
