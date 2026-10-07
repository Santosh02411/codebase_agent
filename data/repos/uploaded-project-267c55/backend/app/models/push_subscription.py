"""
PushSubscriptionDB: stores browser Web Push subscriptions so a customer
can get a real OS-level notification (even with the tab closed) when
their delivery's status changes — no third-party account needed, unlike
SMS/WhatsApp. Web Push is a free, open, standardized browser API backed
by VAPID keys this project generates itself (see services/push.py).

Also used for STAFF (agent/dispatcher/admin) subscriptions — an agent
gets notified the moment they're assigned a new delivery, and a
dispatcher/admin gets notified the moment a new unassigned customer
order lands in their queue. Same table, same mechanism; exactly one of
customer_id or user_id is set per row depending on who subscribed
(see routes/customer_dashboard.py for the customer side,
routes/users.py for the staff side).

One subscriber can have multiple subscriptions (different browsers/
devices) -- each is a separate row, keyed by its unique endpoint URL.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime
from pydantic import BaseModel
from typing import Optional

from app.db.session import Base


class PushSubscriptionDB(Base):
    __tablename__ = "push_subscriptions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    customer_id = Column(String, index=True, nullable=True)
    user_id = Column(String, index=True, nullable=True)  # staff (agent/dispatcher/admin) subscriber — see module docstring
    endpoint = Column(String, nullable=False, unique=True)
    p256dh = Column(String, nullable=False)
    auth = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False)


class PushSubscriptionCreate(BaseModel):
    endpoint: str
    keys: dict  # {"p256dh": "...", "auth": "..."} -- the raw shape the browser's PushManager gives us
