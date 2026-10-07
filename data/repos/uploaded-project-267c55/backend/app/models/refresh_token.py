"""
Refresh tokens for STAFF sessions (UserDB) — this is what makes the
access token (a short-lived JWT, see services/auth.py's
ACCESS_TOKEN_EXPIRE_MINUTES) tolerable to keep short without logging
someone out every 30 minutes: the frontend silently trades a valid
refresh token for a new access token (see POST /auth/refresh) well
before the access token expires.

Design choices, and why:

- Stored HASHED, not plaintext, unlike PasswordResetTokenDB. A
  password reset token is single-use and expires in 30 minutes — a
  narrow exposure window even if the DB were dumped. A refresh token
  lives for RefreshTokenDB's much longer expiry and is exactly as
  powerful as a login credential for that whole window, so a DB dump
  should not be enough to hand over a live session the way a
  plaintext token would. Hashed with a fast SHA-256 (via
  services.auth.hash_refresh_token), not the slow bcrypt used for
  passwords — bcrypt's deliberate slowness defends against brute-forcing
  a low-entropy human password; this token is already a long, random,
  high-entropy string, so a fast one-way hash is the correct tool, not
  a slow one that would need a would-be attacker to already have the
  exact token in hand to matter.

- Rotated on every use (see POST /auth/refresh): each refresh call
  issues a brand-new refresh token AND marks the one just used as
  spent (`used=True`, `replaced_by_id` pointing at the new row). A
  refresh token is good for exactly one refresh, not "log in once,
  reuse this token forever."

- `used=True` + presented again -> theft signal, not just "expired,
  log in again": if someone presents an already-used refresh token,
  that's exactly what you'd see if an attacker copied a token and both
  the real user and the attacker are now racing to redeem it. The
  route revokes the ENTIRE remaining token chain for that user in
  response (see routes/auth.py), not just the one token, since at that
  point neither party's copy of the chain can be trusted.

- `revoked_at` (separate from `used`) is set by an explicit logout
  (POST /auth/logout) or by the theft-detection response above — this
  is the actual "revoke early" capability an access-token-only scheme
  never had: an access token, once issued, could not be invalidated
  before its own expiry no matter what happened server-side. A
  compromised or logged-out refresh token can be shut off immediately;
  the short-lived access token it would have refreshed simply expires
  on its own shortly after and is never renewed.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import Column, String, DateTime, Boolean
from pydantic import BaseModel
from typing import Optional

from app.db.session import Base

REFRESH_TOKEN_EXPIRE_DAYS = 30


class RefreshTokenDB(Base):
    __tablename__ = "refresh_tokens"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, index=True, nullable=False)
    token_hash = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )
    used = Column(Boolean, nullable=False, default=False)
    revoked_at = Column(DateTime, nullable=True)
    replaced_by_id = Column(String, nullable=True)

    # Phase 17: session metadata, captured once at the ORIGINAL login
    # and carried forward through rotation (see routes/auth.py's
    # refresh_access_token, which copies these onto the new row rather
    # than re-detecting them) — so "Active Sessions" shows what device
    # actually logged in, not just whatever made the most recent silent
    # refresh call.
    device_info = Column(String, nullable=True)  # a short parsed label, e.g. "Chrome on Windows" — see services/security.py's parse_user_agent
    ip_address = Column(String, nullable=True)


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class RefreshTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
