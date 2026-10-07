"""
Security & session management service logic (Phase 17): user-agent
parsing, login history/security event recording, suspicious-login
detection, account lockout, password history, and 2FA recovery codes.
"""

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.user import UserDB
from app.models.refresh_token import RefreshTokenDB
from app.models.security import LoginHistoryDB, SecurityEventDB, PasswordHistoryDB, RecoveryCodeDB
from app.services.auth import verify_password

MAX_FAILED_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15
PASSWORD_HISTORY_LIMIT = 5  # how many previous passwords are checked against for reuse
RECOVERY_CODE_COUNT = 10
SUSPICIOUS_LOGIN_LOOKBACK = 20  # how many recent successful logins are checked for a matching IP before a new one is flagged


def parse_user_agent(user_agent: Optional[str]) -> str:
    """
    A short, human-readable label — NOT a full parser library (adding
    one for a handful of common cases is more dependency than this
    project's needs justify). Falls back to "Unknown device" for
    anything it doesn't recognize rather than guessing wrong.
    """
    if not user_agent:
        return "Unknown device"

    browser = "Unknown browser"
    if "Edg/" in user_agent:
        browser = "Edge"
    elif "Chrome/" in user_agent and "Chromium" not in user_agent:
        browser = "Chrome"
    elif "Firefox/" in user_agent:
        browser = "Firefox"
    elif "Safari/" in user_agent and "Chrome" not in user_agent:
        browser = "Safari"

    os_name = "Unknown OS"
    if "Windows" in user_agent:
        os_name = "Windows"
    elif "Mac OS X" in user_agent:
        os_name = "macOS"
    elif "Android" in user_agent:
        os_name = "Android"
    elif "iPhone" in user_agent or "iPad" in user_agent:
        os_name = "iOS"
    elif "Linux" in user_agent:
        os_name = "Linux"

    return f"{browser} on {os_name}"


def client_ip(request) -> Optional[str]:
    """Prefers X-Forwarded-For's first hop (this app sits behind a reverse proxy in real deployment) and falls back to the direct connection."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


# ---------- Login history & security events ----------

def record_login_history(db: Session, user_id: str, org_id: Optional[str], event_type: str, ip_address: Optional[str], device_info: Optional[str]) -> LoginHistoryDB:
    entry = LoginHistoryDB(user_id=user_id, org_id=org_id, event_type=event_type, ip_address=ip_address, device_info=device_info)
    db.add(entry)
    db.commit()
    return entry


def record_security_event(db: Session, user_id: str, org_id: str, event_type: str, detail: Optional[str] = None) -> SecurityEventDB:
    entry = SecurityEventDB(user_id=user_id, org_id=org_id, event_type=event_type, detail=detail)
    db.add(entry)
    db.commit()
    return entry


def is_suspicious_login(db: Session, user_id: str, ip_address: Optional[str]) -> bool:
    """
    Flags a login as suspicious when it comes from an IP that hasn't
    appeared in this user's last SUSPICIOUS_LOGIN_LOOKBACK successful
    logins. A user's very FIRST successful login is never flagged —
    there's no history yet to compare against, so "new IP" isn't
    meaningful information at that point.
    """
    if not ip_address:
        return False
    recent = db.query(LoginHistoryDB).filter(
        LoginHistoryDB.user_id == user_id, LoginHistoryDB.event_type.in_(["login_success", "suspicious_login"]),
    ).order_by(LoginHistoryDB.created_at.desc()).limit(SUSPICIOUS_LOGIN_LOOKBACK).all()
    if not recent:
        return False
    known_ips = {r.ip_address for r in recent if r.ip_address}
    return ip_address not in known_ips


# ---------- Account lockout ----------

def is_locked_out(user: UserDB) -> bool:
    return user.locked_until is not None and user.locked_until > datetime.utcnow()


def register_failed_login(db: Session, user: UserDB) -> None:
    user.failed_login_count += 1
    if user.failed_login_count >= MAX_FAILED_LOGIN_ATTEMPTS:
        user.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
        record_security_event(db, user.id, user.org_id, "account_locked", detail=f"{user.failed_login_count} failed login attempts")
    db.commit()


def register_successful_login(db: Session, user: UserDB) -> None:
    user.failed_login_count = 0
    user.locked_until = None
    db.commit()


# ---------- Password history ----------

def is_password_reused(db: Session, user_id: str, new_password: str) -> bool:
    recent = db.query(PasswordHistoryDB).filter(PasswordHistoryDB.user_id == user_id).order_by(PasswordHistoryDB.created_at.desc()).limit(PASSWORD_HISTORY_LIMIT).all()
    return any(verify_password(new_password, entry.hashed_password) for entry in recent)


def record_password_history(db: Session, user_id: str, hashed_password: str) -> None:
    db.add(PasswordHistoryDB(user_id=user_id, hashed_password=hashed_password))
    db.commit()
    # Prune anything beyond the limit so this table doesn't grow unbounded.
    old_entries = db.query(PasswordHistoryDB).filter(PasswordHistoryDB.user_id == user_id).order_by(PasswordHistoryDB.created_at.desc()).offset(PASSWORD_HISTORY_LIMIT).all()
    for entry in old_entries:
        db.delete(entry)
    if old_entries:
        db.commit()


# ---------- 2FA recovery codes ----------

def _hash_recovery_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def generate_recovery_codes(db: Session, user_id: str) -> list:
    """
    Invalidates any existing unused codes (a fresh generate call is a
    full reset, not an addition — matching how real recovery-code UIs
    work, so a user can't end up with an ever-growing, hard-to-track
    pile of half-used code sets) and returns the new raw codes ONCE.
    """
    db.query(RecoveryCodeDB).filter(RecoveryCodeDB.user_id == user_id, RecoveryCodeDB.used == False).delete()  # noqa: E712
    raw_codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = f"{secrets.token_hex(4)}-{secrets.token_hex(4)}"  # e.g. "a1b2c3d4-e5f6a7b8", easy to read/type back
        raw_codes.append(raw)
        db.add(RecoveryCodeDB(user_id=user_id, code_hash=_hash_recovery_code(raw)))
    db.commit()
    return raw_codes


def verify_and_consume_recovery_code(db: Session, user_id: str, code: str) -> bool:
    code_hash = _hash_recovery_code(code.strip())
    entry = db.query(RecoveryCodeDB).filter(RecoveryCodeDB.user_id == user_id, RecoveryCodeDB.code_hash == code_hash, RecoveryCodeDB.used == False).first()  # noqa: E712
    if not entry:
        return False
    entry.used = True
    entry.used_at = datetime.utcnow()
    db.commit()
    return True


# ---------- Sessions ----------

def revoke_session(db: Session, session: RefreshTokenDB) -> None:
    session.revoked_at = datetime.utcnow()
    db.commit()


def revoke_all_sessions(db: Session, user_id: str, except_session_id: Optional[str] = None) -> int:
    q = db.query(RefreshTokenDB).filter(RefreshTokenDB.user_id == user_id, RefreshTokenDB.revoked_at.is_(None))
    if except_session_id:
        q = q.filter(RefreshTokenDB.id != except_session_id)
    count = q.update({"revoked_at": datetime.utcnow()})
    db.commit()
    return count
