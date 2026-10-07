"""
Bulk delivery import — lets a dispatcher create many deliveries at once
(from a CSV) instead of assigning one at a time.

Design decision: each row is validated and processed independently, and a
bad row (unknown agent, missing order ID) does NOT fail the whole batch —
it's reported as a per-row failure while every valid row still succeeds.
A single typo in row 47 of a 200-row CSV souldn't force the dispatcher to
fix and re-upload everything; partial success with a clear per-row report
is much more usable for a real bulk-upload workflow.
"""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.session import get_db
from app.models.delivery import DeliveryRecordDB, DeliveryStatus
from app.models.user import UserDB, UserRole
from app.models.customer import CustomerDB
from app.routes.deliveries import require_dispatcher
from app.services.history import record_history_entry
from app.services.notifications import notify_customer_of_status_change

router = APIRouter(prefix="/deliveries", tags=["bulk-import"])


class BulkImportRow(BaseModel):
    """One row from the dispatcher's CSV, already parsed into fields."""
    order_id: str
    agent_username: str
    notes: Optional[str] = None
    zone: Optional[str] = None
    expected_by: Optional[datetime] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None


class BulkImportRequest(BaseModel):
    rows: List[BulkImportRow]


class BulkImportRowResult(BaseModel):
    row_number: int
    order_id: str
    success: bool
    error: Optional[str] = None
    delivery_id: Optional[str] = None


class BulkImportResponse(BaseModel):
    results: List[BulkImportRowResult]
    success_count: int
    failure_count: int


@router.post("/bulk-import", response_model=BulkImportResponse)
def bulk_import_deliveries(
    payload: BulkImportRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher),
):
    results: List[BulkImportRowResult] = []
    success_count = 0
    failure_count = 0

    for index, row in enumerate(payload.rows, start=1):
        row_number = index

        # ---- Validate this row ----
        if not row.order_id or not row.order_id.strip():
            results.append(BulkImportRowResult(
                row_number=row_number, order_id=row.order_id or "",
                success=False, error="Order ID is required and cannot be blank.",
            ))
            failure_count += 1
            continue

        agent = db.query(UserDB).filter(
            UserDB.username == row.agent_username,
            UserDB.role == UserRole.agent,
            UserDB.org_id == current_user.org_id,
        ).first()

        if not agent:
            results.append(BulkImportRowResult(
                row_number=row_number, order_id=row.order_id,
                success=False,
                error=f"No agent found with username '{row.agent_username}' in your organization.",
            ))
            failure_count += 1
            continue

        # ---- Row is valid — create the delivery ----
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        expected_by = row.expected_by
        if expected_by and expected_by.tzinfo is not None:
            expected_by = expected_by.astimezone(timezone.utc).replace(tzinfo=None)

        new_delivery = DeliveryRecordDB(
            id=str(uuid.uuid4()),
            agent_id=agent.id,
            order_id=row.order_id.strip(),
            status=DeliveryStatus.picked_up,
            notes=row.notes,
            location_note=None,
            zone=row.zone,
            expected_by=expected_by,
            created_at=now,
            updated_at=now,
            org_id=current_user.org_id,
            customer_email=row.customer_email,
            customer_phone=row.customer_phone,
        )

        if new_delivery.customer_email:
            matching_customer = db.query(CustomerDB).filter(
                CustomerDB.email == new_delivery.customer_email
            ).first()
            if matching_customer:
                new_delivery.customer_id = matching_customer.id

        db.add(new_delivery)
        db.commit()
        db.refresh(new_delivery)

        record_history_entry(
            db,
            delivery_id=new_delivery.id,
            changed_by_user_id=current_user.id,
            changed_by_display_name=current_user.display_name,
            old_status=None,
            new_status=new_delivery.status,
            changed_at=now,
            note=f"Created via bulk import, assigned to {agent.display_name}",
        )
        notify_customer_of_status_change(
            db,
            delivery_id=new_delivery.id,
            order_id=new_delivery.order_id,
            new_status="confirmed",
            customer_email=new_delivery.customer_email,
            customer_phone=new_delivery.customer_phone,
            customer_id=new_delivery.customer_id,
        )

        results.append(BulkImportRowResult(
            row_number=row_number, order_id=row.order_id,
            success=True, delivery_id=new_delivery.id,
        ))
        success_count += 1

    return BulkImportResponse(
        results=results, success_count=success_count, failure_count=failure_count
    )
