"""
Admin analytics dashboard: revenue, order volume, fulfillment breakdown,
top products, and low-stock alerts for the caller's own organization.

Deliberately computed on-the-fly from existing Order/OrderItem/
DeliveryRecord rows rather than maintained as a running total anywhere -
at this project's scale that's simpler and can never drift from the
underlying data (no "the dashboard says X but the orders list says Y"
bugs), at the cost of doing real aggregation work on every request
rather than reading a cached number. Fine for a single org's order
volume; a much larger deployment would move this to a scheduled
rollup table instead.
"""

from datetime import datetime, timedelta
from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import UserDB
from app.models.order import OrderDB, OrderItemDB, OrderStatus
from app.models.delivery import DeliveryRecordDB, DeliveryStatus
from app.models.product import ProductDB
from app.models.analytics import (
    AnalyticsOut, RevenueByDayOut, TopProductOut, DeliveryStatusBreakdownOut, LowStockProductOut,
)
from app.routes.admin import require_admin

router = APIRouter(prefix="/admin/analytics", tags=["analytics"])

LOW_STOCK_THRESHOLD = 5


@router.get("/", response_model=AnalyticsOut)
def get_analytics(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_admin),
):
    org_id = current_user.org_id
    since = datetime.utcnow() - timedelta(days=days)

    paid_orders = db.query(OrderDB).filter(
        OrderDB.org_id == org_id,
        OrderDB.status == OrderStatus.paid,
        OrderDB.created_at >= since,
    ).all()

    total_revenue = round(sum(o.total for o in paid_orders), 2)
    total_orders = len(paid_orders)
    average_order_value = round(total_revenue / total_orders, 2) if total_orders else 0.0
    total_discount_given = round(sum(o.discount_amount for o in paid_orders), 2)
    total_delivery_fees_collected = round(sum(o.delivery_fee for o in paid_orders), 2)
    total_tax_collected = round(sum(o.tax_amount for o in paid_orders), 2)

    refunded_orders = [o for o in paid_orders if o.refund_status == "refunded"]
    total_refunded = round(sum(o.total for o in refunded_orders), 2)
    refunded_order_count = len(refunded_orders)

    # Revenue by day, zero-filled for every day in the window (not just
    # days that had an order) so a frontend chart has a continuous axis.
    by_day: dict = defaultdict(lambda: {"revenue": 0.0, "order_count": 0})
    for order in paid_orders:
        day_key = order.created_at.strftime("%Y-%m-%d")
        by_day[day_key]["revenue"] += order.total
        by_day[day_key]["order_count"] += 1

    revenue_by_day = []
    for i in range(days - 1, -1, -1):
        day = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
        entry = by_day.get(day, {"revenue": 0.0, "order_count": 0})
        revenue_by_day.append(RevenueByDayOut(date=day, revenue=round(entry["revenue"], 2), order_count=entry["order_count"]))

    # Top products by revenue, from order items on those same paid orders.
    paid_order_ids = [o.id for o in paid_orders]
    product_totals: dict = defaultdict(lambda: {"product_name": "", "quantity_sold": 0, "revenue": 0.0})
    if paid_order_ids:
        items = db.query(OrderItemDB).filter(OrderItemDB.order_id.in_(paid_order_ids)).all()
        for item in items:
            entry = product_totals[item.product_id]
            entry["product_name"] = item.product_name
            entry["quantity_sold"] += item.quantity
            entry["revenue"] += item.unit_price * item.quantity
    top_products = sorted(
        (TopProductOut(product_id=pid, product_name=v["product_name"], quantity_sold=v["quantity_sold"], revenue=round(v["revenue"], 2))
         for pid, v in product_totals.items()),
        key=lambda p: p.revenue,
        reverse=True,
    )[:5]

    # Delivery fulfillment breakdown — org-wide, not time-windowed, so it
    # always reflects the true current state of every delivery in flight
    # (a delivery placed 40 days ago but still "picked_up" today should
    # still show up, even with days=30).
    breakdown = DeliveryStatusBreakdownOut()
    # Simple per-status count loop (not a single group-by) — org-scale
    # here is small enough that six extra queries costs nothing, and
    # this reads far more clearly than assembling a group-by result set.
    for status in DeliveryStatus:
        count = db.query(DeliveryRecordDB).filter(
            DeliveryRecordDB.org_id == org_id,
            DeliveryRecordDB.status == status,
        ).count()
        setattr(breakdown, status.value, count)

    low_stock = db.query(ProductDB).filter(
        ProductDB.org_id == org_id,
        ProductDB.is_active == True,  # noqa: E712
        ProductDB.stock_quantity.isnot(None),
        ProductDB.stock_quantity <= LOW_STOCK_THRESHOLD,
    ).order_by(ProductDB.stock_quantity.asc()).all()

    return AnalyticsOut(
        period_days=days,
        total_revenue=total_revenue,
        total_orders=total_orders,
        average_order_value=average_order_value,
        total_discount_given=total_discount_given,
        total_delivery_fees_collected=total_delivery_fees_collected,
        total_tax_collected=total_tax_collected,
        total_refunded=total_refunded,
        refunded_order_count=refunded_order_count,
        delivery_status_breakdown=breakdown,
        revenue_by_day=revenue_by_day,
        top_products=top_products,
        low_stock_products=[LowStockProductOut(id=p.id, name=p.name, stock_quantity=p.stock_quantity) for p in low_stock],
    )
