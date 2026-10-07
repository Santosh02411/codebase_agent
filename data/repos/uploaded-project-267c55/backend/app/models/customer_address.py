"""
CustomerAddressDB: a customer's saved delivery addresses (home, work,
etc.), so they don't have to type a full address out from scratch every
time — the standard "address book" feature on any e-commerce account.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Boolean
from pydantic import BaseModel
from typing import Optional

from app.db.session import Base


class CustomerAddressDB(Base):
    __tablename__ = "customer_addresses"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    customer_id = Column(String, index=True, nullable=False)
    label = Column(String, nullable=False)          # "Home", "Work", etc.
    address_line = Column(String, nullable=False)
    city = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, nullable=False)


class CustomerAddressCreate(BaseModel):
    label: str
    address_line: str
    city: Optional[str] = None
    phone: Optional[str] = None
    is_default: bool = False


class CustomerAddressOut(BaseModel):
    id: str
    label: str
    address_line: str
    city: Optional[str] = None
    phone: Optional[str] = None
    is_default: bool
    created_at: datetime

    class Config:
        from_attributes = True
