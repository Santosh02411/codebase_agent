"""
ExpoPushTokenDB: stores an Expo push token so the mobile agent app
(mobile/) can get a real OS-level notification — even with the app
fully closed — the moment a delivery is assigned/unassigned or another
staff notification fires. Mirrors PushSubscriptionDB's role for the
web app exactly, just for a different delivery mechanism: a browser's
Web Push subscription (endpoint + keys, delivered via the browser
vendor's own push service, authenticated with this project's VAPID
keypair — see models/push_subscription.py and services/push.py) vs.
an Expo push token (a single opaque string, delivered via Expo's own
push notification service — see services/expo_push.py).

Staff-only (no customer_id column) — unlike the web app, the mobile
app is agent-only by design (see mobile/README.md), so there's no
customer-facing Expo push to support yet.

One user can have multiple tokens (e.g. the same agent logged into the
app on two different phones) — each is a separate row, keyed by its
unique token string, same "one row per device" shape as
PushSubscriptionDB's endpoint uniqueness.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime
from pydantic import BaseModel

from app.db.session import Base


class ExpoPushTokenDB(Base):
    __tablename__ = "expo_push_tokens"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, index=True, nullable=False)
    token = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False)


class ExpoPushTokenRegister(BaseModel):
    token: str
