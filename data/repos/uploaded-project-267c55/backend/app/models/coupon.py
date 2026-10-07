"""
CouponDB: a promo code an org's admin/dispatcher creates, that a
customer can apply at checkout for a discount. Org-scoped, same as
products — one org's coupon code is entirely independent of another
org's code of the same text (two different stores can both run "SAVE10").

Two discount shapes, same as basically every real coupon system:
  - percent: knock a % off the (pre-tax, pre-delivery-fee) subtotal
  - flat:    knock a fixed rupee amount off

Usage limits are enforced against `used_count`, incremented only once a
coupon's order actually reaches `paid` (see routes/checkout.py) — an
abandoned or failed checkout should never burn through a limited coupon's
uses.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, Enum as SqlEnum, UniqueConstraint
from pydantic import BaseModel, Field
from typing import Optional

from app.db.session import Base


class DiscountType(str, enum.Enum):
    percent = "percent"
    flat = "flat"


class CouponDB(Base):
    __tablename__ = "coupons"
    __table_args__ = (UniqueConstraint("org_id", "code", name="uq_coupon_code_per_org"),)

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    code = Column(String, index=True, nullable=False)  # stored upper-cased — see routes/coupons.py
    discount_type = Column(SqlEnum(DiscountType), nullable=False)
    discount_value = Column(Float, nullable=False)  # a percent (0-100) or a flat rupee amount, per discount_type
    min_order_value = Column(Float, nullable=True)  # None = no minimum
    max_uses = Column(Integer, nullable=True)  # None = unlimited
    used_count = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime, nullable=True)  # None = never expires
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CouponCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    discount_type: DiscountType
    discount_value: float = Field(gt=0)
    min_order_value: Optional[float] = Field(default=None, ge=0)
    max_uses: Optional[int] = Field(default=None, ge=1)
    expires_at: Optional[datetime] = None
    is_active: bool = True


class CouponUpdate(BaseModel):
    discount_type: Optional[DiscountType] = None
    discount_value: Optional[float] = Field(default=None, gt=0)
    min_order_value: Optional[float] = Field(default=None, ge=0)
    max_uses: Optional[int] = Field(default=None, ge=1)
    expires_at: Optional[datetime] = None
    is_active: Optional[bool] = None


class CouponOut(BaseModel):
    id: str
    org_id: str
    code: str
    discount_type: DiscountType
    discount_value: float
    min_order_value: Optional[float] = None
    max_uses: Optional[int] = None
    used_count: int
    expires_at: Optional[datetime] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class CouponApply(BaseModel):
    code: str


class CouponPreviewOut(BaseModel):
    """What applying a coupon to the current cart would do — shown before checkout."""
    code: str
    discount_amount: float
    subtotal: float
    new_subtotal: float
