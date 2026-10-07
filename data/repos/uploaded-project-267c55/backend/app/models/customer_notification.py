"""
In-app notifications for the customer dashboard — this is the REAL,
user-facing notification channel (visible directly in the product after
logging in), separate from the email/SMS console-log simulation in
services/notifications.py. A customer sees these the moment they open
their dashboard; they don't need access to server logs, an email inbox,
or a phone to know their order status changed.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Boolean
from pydantic import BaseModel

from app.db.session import Base


class CustomerNotificationDB(Base):
    __tablename__ = "customer_notifications"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    customer_id = Column(String, index=True, nullable=False)
    delivery_id = Column(String, nullable=False)
    order_id = Column(String, nullable=False)
    message = Column(String, nullable=False)
    is_read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CustomerNotificationOut(BaseModel):
    id: str
    delivery_id: str
    order_id: str
    message: str
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True
