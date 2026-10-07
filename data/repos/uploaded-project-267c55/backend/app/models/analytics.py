"""
Response schemas for the admin analytics dashboard (routes/analytics.py).
No database table here - everything is computed on read from existing
Order/OrderItem/DeliveryRecord rows, so there's nothing to keep in sync
and no risk of a cached number drifting from reality.
"""

from pydantic import BaseModel
from typing import List


class RevenueByDayOut(BaseModel):
    date: str  # "YYYY-MM-DD"
    revenue: float
    order_count: int


class TopProductOut(BaseModel):
    product_id: str
    product_name: str
    quantity_sold: int
    revenue: float


class DeliveryStatusBreakdownOut(BaseModel):
    pending: int = 0
    picked_up: int = 0
    out_for_delivery: int = 0
    delivered: int = 0
    failed_attempt: int = 0
    cancelled: int = 0


class LowStockProductOut(BaseModel):
    id: str
    name: str
    stock_quantity: int


class AnalyticsOut(BaseModel):
    period_days: int
    total_revenue: float
    total_orders: int
    average_order_value: float
    total_discount_given: float
    total_delivery_fees_collected: float
    total_tax_collected: float
    total_refunded: float
    refunded_order_count: int
    delivery_status_breakdown: DeliveryStatusBreakdownOut
    revenue_by_day: List[RevenueByDayOut]
    top_products: List[TopProductOut]
    low_stock_products: List[LowStockProductOut]
