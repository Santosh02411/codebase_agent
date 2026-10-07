"""
Shared coupon eligibility + discount math, used by both the checkout-
preview endpoint (routes/checkout.py's validate-coupon) and the actual
checkout endpoint — so "what discount would I get" and "what discount
did I actually get" can never disagree.
"""

from datetime import datetime
from typing import Tuple

from sqlalchemy.orm import Session

from app.models.coupon import CouponDB, DiscountType


class CouponError(Exception):
    """Raised with a customer-facing message for any ineligible coupon."""
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def find_and_validate_coupon(db: Session, org_id: str, code: str, subtotal: float) -> CouponDB:
    """
    Looks up a coupon by code (case-insensitive) scoped to one org, and
    checks every eligibility rule against the given cart subtotal. Raises
    CouponError with a specific, customer-facing reason on any failure;
    returns the CouponDB row if everything checks out.
    """
    normalized = code.strip().upper()
    coupon = db.query(CouponDB).filter(
        CouponDB.org_id == org_id,
        CouponDB.code == normalized,
    ).first()
    if not coupon:
        raise CouponError("That coupon code isn't valid for this store.")
    if not coupon.is_active:
        raise CouponError("That coupon is no longer active.")
    if coupon.expires_at and datetime.utcnow() > coupon.expires_at:
        raise CouponError("That coupon has expired.")
    if coupon.max_uses is not None and coupon.used_count >= coupon.max_uses:
        raise CouponError("That coupon has already been fully redeemed.")
    if coupon.min_order_value is not None and subtotal < coupon.min_order_value:
        raise CouponError(f"This coupon needs a minimum order of ₹{coupon.min_order_value:.2f}.")
    return coupon


def compute_discount(coupon: CouponDB, subtotal: float) -> float:
    """
    The actual discount amount for a subtotal, never exceeding the
    subtotal itself (a flat-₹500-off coupon on a ₹200 order discounts
    ₹200, not ₹500 into negative territory).
    """
    if coupon.discount_type == DiscountType.percent:
        raw = subtotal * (coupon.discount_value / 100.0)
    else:
        raw = coupon.discount_value
    return round(min(raw, subtotal), 2)


def validate_and_price_coupon(db: Session, org_id: str, code: str, subtotal: float) -> Tuple[CouponDB, float]:
    """Convenience wrapper: validate, then compute the discount in one call."""
    coupon = find_and_validate_coupon(db, org_id, code, subtotal)
    return coupon, compute_discount(coupon, subtotal)
