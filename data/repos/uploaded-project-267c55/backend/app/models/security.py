"""
Security & session management (Phase 17) — everything that isn't
already covered by the existing auth system (JWT access tokens,
RefreshTokenDB rotation/theft-detection, TOTP/email 2FA, password
reset, CAPTCHA, rate limiting). This adds: login history, a broader
security-activity log, 2FA recovery codes, and password history (to
block immediate password reuse).

Account lockout and "Active Sessions" don't get their own tables —
lockout is two columns on UserDB (see models/user.py), and "Active
Sessions" is just RefreshTokenDB rows filtered to not-revoked/
not-expired (see routes/auth.py's GET /auth/sessions) — no need for a
parallel session table when RefreshTokenDB already IS the session
record.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Boolean
from pydantic import BaseModel
from typing import Optional, List

from app.db.session import Base

LOGIN_EVENT_TYPES = {"login_success", "login_failed", "suspicious_login"}
SECURITY_EVENT_TYPES = {
    "password_changed", "password_reset", "2fa_enabled", "2fa_disabled",
    "session_revoked", "all_sessions_revoked", "account_locked",
    "recovery_codes_generated", "recovery_code_used",
}


class LoginHistoryDB(Base):
    __tablename__ = "login_history"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, index=True, nullable=False)
    org_id = Column(String, index=True, nullable=True)  # null for a failed login where the username didn't even resolve to a real user

    event_type = Column(String, nullable=False)  # one of LOGIN_EVENT_TYPES
    ip_address = Column(String, nullable=True)
    device_info = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class SecurityEventDB(Base):
    __tablename__ = "security_events"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, index=True, nullable=False)
    org_id = Column(String, index=True, nullable=False)

    event_type = Column(String, nullable=False)  # one of SECURITY_EVENT_TYPES
    detail = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class PasswordHistoryDB(Base):
    __tablename__ = "password_history"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)  # bcrypt hash, same algorithm/cost as UserDB.hashed_password — never the plaintext
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class RecoveryCodeDB(Base):
    __tablename__ = "recovery_codes"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, index=True, nullable=False)
    code_hash = Column(String, nullable=False)  # SHA-256, same reasoning as ApiKeyDB (Phase 14): high-entropy random code, nothing to brute-force via a rainbow table
    used = Column(Boolean, nullable=False, default=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# ---------- Pydantic Schemas ----------

class SessionOut(BaseModel):
    id: str
    device_info: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: datetime
    is_current: bool = False

    class Config:
        from_attributes = True


class LoginHistoryOut(BaseModel):
    id: str
    event_type: str
    ip_address: Optional[str] = None
    device_info: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SecurityEventOut(BaseModel):
    id: str
    event_type: str
    detail: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class RecoveryCodesGenerateRequest(BaseModel):
    password: str


class RecoveryCodesOut(BaseModel):
    codes: List[str]  # ONLY ever populated in the response to the generate call itself — never retrievable again after this


class RecoveryCodeUseRequest(BaseModel):
    challenge_token: str
    recovery_code: str
