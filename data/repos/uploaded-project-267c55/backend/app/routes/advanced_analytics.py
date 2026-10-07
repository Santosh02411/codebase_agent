"""
Advanced analytics routes (Phase 15) — admin-only, same tier as the
base analytics dashboard (routes/analytics.py). All computed live
from existing rows on every request, same "never drift from the
underlying data" tradeoff the base dashboard already documents and
accepts, rather than a maintained rollup table.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import UserDB
from app.routes.admin import require_admin
from app.services import advanced_analytics as svc

router = APIRouter(prefix="/admin/analytics/advanced", tags=["analytics"])


@router.get("/")
def get_advanced_analytics(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_admin),
):
    org_id = current_user.org_id
    since = datetime.utcnow() - timedelta(days=days)

    return {
        "period_days": days,
        "agent_productivity": svc.agent_productivity(db, org_id, since),
        "failed_delivery_analytics": svc.failed_delivery_analytics(db, org_id, since),
        "return_and_cancellation_analytics": svc.return_and_cancellation_analytics(db, org_id, since),
        "customer_retention": svc.customer_retention(db, org_id, since),
        "revenue_breakdowns": svc.revenue_breakdowns(db, org_id, since),
        "profit_margin": svc.profit_margin_analytics(db, org_id, since),
        "trend_and_forecast": svc.revenue_trend_and_forecast(db, org_id, days),
    }
