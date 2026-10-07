"""
Advanced analytics (Phase 15) — the reports NOT already covered by an
existing, more specific analytics endpoint elsewhere in this project:
SLA analytics lives in routes/sla.py, route efficiency/heatmaps in
routes/route_analytics.py, RTO analytics in routes/rto.py, support
analytics in routes/support.py, and fleet utilization in
routes/fleet.py. Rather than duplicating any of those, this module
adds exactly what's genuinely missing: agent productivity, failed-
delivery breakdown, return/cancellation rates, customer retention,
revenue by category/payment method, profit margin, and a naive
trend/forecast.
"""

from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional

from sqlalchemy.orm import Session

from app.models.delivery import DeliveryRecordDB, DeliveryStatus
from app.models.delivery_attempt import DeliveryAttemptDB
from app.models.order import OrderDB, OrderItemDB, OrderStatus
from app.models.product import ProductDB
from app.models.return_request import ReturnRequestDB
from app.models.user import UserDB, UserRole


def agent_productivity(db: Session, org_id: str, since: datetime) -> list:
    """
    Per-agent delivered/failed counts and on-time rate over the window.
    Distinct from Phase 11's fleet utilization (which counts deliveries
    per VEHICLE) and Phase 2's SLA analytics (which reports on-time %
    org-wide, not broken out per agent) — this is the one place that
    slices it by agent.
    """
    agents = db.query(UserDB).filter(UserDB.org_id == org_id, UserDB.role == UserRole.agent).all()
    results = []
    for agent in agents:
        delivered = db.query(DeliveryRecordDB).filter(
            DeliveryRecordDB.org_id == org_id, DeliveryRecordDB.agent_id == agent.id,
            DeliveryRecordDB.status == DeliveryStatus.delivered, DeliveryRecordDB.updated_at >= since,
        ).all()
        failed_count = db.query(DeliveryRecordDB).filter(
            DeliveryRecordDB.org_id == org_id, DeliveryRecordDB.agent_id == agent.id,
            DeliveryRecordDB.status == DeliveryStatus.failed_attempt, DeliveryRecordDB.updated_at >= since,
        ).count()

        on_time = sum(1 for d in delivered if d.sla_status == "met")
        rated = sum(1 for d in delivered if d.sla_status in ("met", "missed"))

        results.append({
            "agent_id": agent.id, "agent_name": agent.display_name,
            "delivered_count": len(delivered), "failed_count": failed_count,
            "on_time_rate": round(on_time / rated * 100, 1) if rated else None,
        })
    return sorted(results, key=lambda r: r["delivered_count"], reverse=True)


def failed_delivery_analytics(db: Session, org_id: str, since: datetime) -> dict:
    """Failure breakdown by reason code, and the failure rate relative to every delivery attempt closed (delivered + failed) in the window."""
    attempts = db.query(DeliveryAttemptDB).filter(DeliveryAttemptDB.org_id == org_id, DeliveryAttemptDB.attempted_at >= since).all()
    failed = [a for a in attempts if a.outcome == "failed_attempt"]
    closed = [a for a in attempts if a.outcome in ("delivered", "failed_attempt")]

    by_reason: dict = defaultdict(int)
    for a in failed:
        by_reason[a.reason_label or "No reason given"] += 1

    return {
        "total_failed": len(failed),
        "failure_rate_percent": round(len(failed) / len(closed) * 100, 1) if closed else 0.0,
        "by_reason": dict(by_reason),
    }


def return_and_cancellation_analytics(db: Session, org_id: str, since: datetime) -> dict:
    returns = db.query(ReturnRequestDB).filter(ReturnRequestDB.org_id == org_id, ReturnRequestDB.requested_at >= since).all()
    by_type: dict = defaultdict(int)
    by_status: dict = defaultdict(int)
    for r in returns:
        by_type[r.request_type.value if hasattr(r.request_type, "value") else r.request_type] += 1
        by_status[r.status.value if hasattr(r.status, "value") else r.status] += 1

    total_deliveries = db.query(DeliveryRecordDB).filter(DeliveryRecordDB.org_id == org_id, DeliveryRecordDB.created_at >= since).count()
    cancelled = db.query(DeliveryRecordDB).filter(
        DeliveryRecordDB.org_id == org_id, DeliveryRecordDB.status == DeliveryStatus.cancelled,
        DeliveryRecordDB.updated_at >= since,
    ).count()

    return {
        "total_return_requests": len(returns),
        "by_type": dict(by_type),
        "by_status": dict(by_status),
        "total_cancelled": cancelled,
        "cancellation_rate_percent": round(cancelled / total_deliveries * 100, 1) if total_deliveries else 0.0,
    }


def customer_retention(db: Session, org_id: str, since: datetime) -> dict:
    """Repeat-order rate over the window: what fraction of customers who ordered placed MORE than one paid order."""
    paid_orders = db.query(OrderDB).filter(OrderDB.org_id == org_id, OrderDB.status == OrderStatus.paid, OrderDB.created_at >= since).all()
    orders_per_customer: dict = defaultdict(int)
    for o in paid_orders:
        orders_per_customer[o.customer_id] += 1

    total_customers = len(orders_per_customer)
    repeat_customers = sum(1 for count in orders_per_customer.values() if count > 1)

    return {
        "unique_customers": total_customers,
        "repeat_customers": repeat_customers,
        "repeat_order_rate_percent": round(repeat_customers / total_customers * 100, 1) if total_customers else 0.0,
    }


def revenue_breakdowns(db: Session, org_id: str, since: datetime) -> dict:
    """Revenue by product category and by payment method — the base analytics endpoint (routes/analytics.py) only reports the org-wide total, never broken out."""
    paid_orders = db.query(OrderDB).filter(OrderDB.org_id == org_id, OrderDB.status == OrderStatus.paid, OrderDB.created_at >= since).all()

    by_payment_method: dict = defaultdict(float)
    for o in paid_orders:
        by_payment_method[o.payment_method] += o.total

    paid_order_ids = [o.id for o in paid_orders]
    by_category: dict = defaultdict(float)
    if paid_order_ids:
        items = db.query(OrderItemDB).filter(OrderItemDB.order_id.in_(paid_order_ids)).all()
        product_ids = {i.product_id for i in items}
        products = {p.id: p for p in db.query(ProductDB).filter(ProductDB.id.in_(product_ids)).all()} if product_ids else {}
        for item in items:
            product = products.get(item.product_id)
            category = product.category if product and product.category else "Uncategorized"
            by_category[category] += item.unit_price * item.quantity

    return {
        "by_payment_method": {k: round(v, 2) for k, v in by_payment_method.items()},
        "by_category": {k: round(v, 2) for k, v in by_category.items()},
    }


def profit_margin_analytics(db: Session, org_id: str, since: datetime) -> dict:
    """
    Only counts line items on products that have a cost_price set —
    both revenue AND cost for a product with no cost_price on record
    are excluded from this calculation (not just its cost), so revenue
    and cost always come from the same subset of items and the margin
    percentage is never distorted by mixing priced and unpriced lines.
    `products_missing_cost_price` tells the admin how much of their
    catalog isn't covered by this report yet.
    """
    paid_orders = db.query(OrderDB).filter(OrderDB.org_id == org_id, OrderDB.status == OrderStatus.paid, OrderDB.created_at >= since).all()
    paid_order_ids = [o.id for o in paid_orders]
    if not paid_order_ids:
        return {"revenue": 0.0, "cost": 0.0, "profit": 0.0, "margin_percent": None, "products_missing_cost_price": 0}

    items = db.query(OrderItemDB).filter(OrderItemDB.order_id.in_(paid_order_ids)).all()
    product_ids = {i.product_id for i in items}
    products = {p.id: p for p in db.query(ProductDB).filter(ProductDB.id.in_(product_ids)).all()}

    revenue = 0.0
    cost = 0.0
    missing_cost = set()
    for item in items:
        product = products.get(item.product_id)
        if product and product.cost_price is not None:
            revenue += item.unit_price * item.quantity
            cost += product.cost_price * item.quantity
        else:
            missing_cost.add(item.product_id)

    profit = revenue - cost
    return {
        "revenue": round(revenue, 2), "cost": round(cost, 2), "profit": round(profit, 2),
        "margin_percent": round(profit / revenue * 100, 1) if revenue else None,
        "products_missing_cost_price": len(missing_cost),
    }


def revenue_trend_and_forecast(db: Session, org_id: str, days: int) -> dict:
    """
    Trend: this window's revenue vs the PRIOR window of equal length
    (% change). Forecast: a naive 7-day projection using the current
    window's daily average — explicitly labeled as such, not
    presented as a real predictive model. A genuine forecasting model
    needs more history and seasonality handling than this project's
    data volume can reliably support; a transparent naive baseline is
    more honest than a black-box number.
    """
    now = datetime.utcnow()
    current_start = now - timedelta(days=days)
    previous_start = current_start - timedelta(days=days)

    current_revenue = sum(
        o.total for o in db.query(OrderDB).filter(
            OrderDB.org_id == org_id, OrderDB.status == OrderStatus.paid, OrderDB.created_at >= current_start,
        ).all()
    )
    previous_revenue = sum(
        o.total for o in db.query(OrderDB).filter(
            OrderDB.org_id == org_id, OrderDB.status == OrderStatus.paid,
            OrderDB.created_at >= previous_start, OrderDB.created_at < current_start,
        ).all()
    )

    change_percent = None
    if previous_revenue > 0:
        change_percent = round((current_revenue - previous_revenue) / previous_revenue * 100, 1)

    daily_average = current_revenue / days if days else 0.0
    naive_7_day_forecast = round(daily_average * 7, 2)

    return {
        "current_period_revenue": round(current_revenue, 2),
        "previous_period_revenue": round(previous_revenue, 2),
        "change_percent": change_percent,
        "naive_7_day_forecast": naive_7_day_forecast,
        "forecast_method": "naive moving average of the current period's daily revenue — not a seasonal or ML model",
    }
