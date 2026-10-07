"""
Email sending, abstracted behind one function so the rest of the app
never needs to know HOW an email actually gets delivered. Used for
password reset links and delivery status-change notifications.

This project has no budget for a paid transactional email service, so by
default, "sending" an email just prints it clearly to the backend
console/log instead of actually delivering it — which is enough to
develop and test the full flow (token generation and expiry for resets;
status text and tracking link for notifications) without needing any
external service at all.

If SMTP_HOST (and the other SMTP_* variables below) are set in the
environment, this switches to actually sending via any standard SMTP
server — for example, a free Gmail account with an "app password" works
here at zero cost. Nothing about the calling code changes based on which
path is used; only this module's internal behavior does.
"""

import os
import smtplib
from email.mime.text import MIMEText

from app.services import monitoring as monitoring_svc

SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "noreply@deliverysync.local")


def send_password_reset_email(to_email: str, reset_link: str) -> None:
    subject = "Reset your Delivery Sync password"
    body = (
        f"Someone requested a password reset for this email address.\n\n"
        f"Reset your password here (link expires in 30 minutes):\n{reset_link}\n\n"
        f"If you didn't request this, you can safely ignore this email."
    )
    _send_email(to_email, subject, body)


def send_customer_password_reset_email(to_email: str, reset_link: str) -> None:
    subject = "Reset your Delivery Sync account password"
    body = (
        f"Someone requested a password reset for your Delivery Sync customer account.\n\n"
        f"Reset your password here (link expires in 30 minutes):\n{reset_link}\n\n"
        f"If you didn't request this, you can safely ignore this email — your password won't be changed."
    )
    _send_email(to_email, subject, body)


def send_verification_email(to_email: str, verify_link: str) -> None:
    subject = "Verify your Delivery Sync email address"
    body = (
        f"Please confirm this is your email address by clicking the link below "
        f"(expires in 48 hours):\n{verify_link}\n\n"
        f"If you didn't create a Delivery Sync account, you can safely ignore this email."
    )
    _send_email(to_email, subject, body)


def send_customer_verification_email(to_email: str, verify_link: str) -> None:
    subject = "Verify your Delivery Sync account email"
    body = (
        f"Please confirm this is your email address by clicking the link below "
        f"(expires in 48 hours):\n{verify_link}\n\n"
        f"If you didn't create a Delivery Sync account, you can safely ignore this email."
    )
    _send_email(to_email, subject, body)


def send_org_welcome_email(to_email: str, display_name: str, org_name: str, invite_code: str) -> None:
    """
    Sent once, right after POST /auth/signup (or the Google OAuth
    signup path) creates a BRAND NEW organization — the person who
    just created it is always its admin (see signup()'s own comment
    on why). Separate from send_verification_email: that one confirms
    the person owns this inbox; this one is the actual "you're set up,
    here's what to do next" welcome message, which is a different job
    and arrives as a second, distinct email rather than being folded
    into the verification one.
    """
    subject = f"Welcome to Delivery Sync — {org_name} is ready"
    body = (
        f"Hi {display_name},\n\n"
        f"Your organization \"{org_name}\" has been created, and you're its admin.\n\n"
        f"Share this invite code with your team so agents and dispatchers can join "
        f"\"{org_name}\" themselves from the Sign Up screen:\n\n"
        f"    {invite_code}\n\n"
        f"You can find this code again anytime from your account settings."
    )
    _send_email(to_email, subject, body)


def send_staff_welcome_email(to_email: str, display_name: str, org_name: str, role: str) -> None:
    """
    Sent once, right after someone JOINS an existing organization via
    invite code (as opposed to creating one — see
    send_org_welcome_email above for that case) as an agent or
    dispatcher.
    """
    role_label = "a dispatcher" if role == "dispatcher" else "an agent"
    subject = f"Welcome to {org_name} on Delivery Sync"
    body = (
        f"Hi {display_name},\n\n"
        f"You've joined \"{org_name}\" on Delivery Sync as {role_label}.\n\n"
        f"You can log in now with the username and password you just created."
    )
    _send_email(to_email, subject, body)


def send_status_notification_email(to_email: str, order_id: str, status_label: str, tracking_link: str) -> None:
    subject = f"Update on your delivery {order_id}"
    body = (
        f"Your order {order_id} is now: {status_label}\n\n"
        f"Track it live here (no login needed):\n{tracking_link}"
    )
    _send_email(to_email, subject, body)


def send_two_factor_code_email(to_email: str, code: str, purpose: str) -> None:
    """
    purpose is "enable_2fa" (confirming the user controls this inbox
    before turning email-based 2FA on) or "login" (a normal sign-in
    second factor) — same email shape either way, just different wording
    so it's clear from the subject line why the code was sent.
    """
    if purpose == "enable_2fa":
        subject = "Confirm email for Delivery Sync two-factor authentication"
        intro = "Use this code to turn on email-based two-factor authentication for your account:"
    else:
        subject = "Your Delivery Sync login code"
        intro = "Use this code to finish logging in:"

    body = (
        f"{intro}\n\n"
        f"    {code}\n\n"
        f"This code expires in 10 minutes. If you didn't request this, you can safely ignore this email."
    )
    _send_email(to_email, subject, body)


def send_security_alert_email(to_email: str, event_description: str, ip_address: str = None, device_info: str = None) -> None:
    """
    Phase 17: a plain security notification — new/suspicious login,
    password changed, 2FA disabled, all sessions logged out. Same
    dev-mode "print instead of send" fallback as every other email in
    this module via _send_email, so this works out of the box without
    SMTP credentials.
    """
    subject = f"Delivery Sync security alert: {event_description}"
    context_lines = []
    if device_info:
        context_lines.append(f"Device: {device_info}")
    if ip_address:
        context_lines.append(f"IP address: {ip_address}")
    context = ("\n" + "\n".join(context_lines) + "\n") if context_lines else ""
    body = (
        f"We noticed the following on your Delivery Sync account:\n\n"
        f"    {event_description}\n"
        f"{context}\n"
        f"If this was you, no action is needed. If you don't recognize this, change your password immediately "
        f"and review your active sessions."
    )
    _send_email(to_email, subject, body)


def _send_email(to_email: str, subject: str, body: str) -> None:
    if not SMTP_HOST:
        # No SMTP configured — this is the default, zero-cost path.
        print("=" * 60)
        print("EMAIL (no SMTP_HOST configured — printed instead of sent)")
        print(f"To: {to_email}")
        print(f"Subject: {subject}")
        print(body)
        print("=" * 60)
        monitoring_svc.record_notification_sent("email", success=True)
        return

    # SMTP_HOST is configured — actually send a real email.
    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = FROM_EMAIL
    message["To"] = to_email

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            if SMTP_USERNAME and SMTP_PASSWORD:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(FROM_EMAIL, [to_email], message.as_string())
        monitoring_svc.record_notification_sent("email", success=True)
    except Exception:
        monitoring_svc.record_notification_sent("email", success=False)
        raise
