"""
Real browser Web Push notifications — unlike SMS/WhatsApp, this needs NO
paid third-party account. It's a free, open W3C standard: the browser
itself (via Chrome/Firefox/etc.'s push service) delivers the message,
authenticated using a VAPID keypair this project owns.

A keypair is generated once and checked in below as a working default —
genuinely functional out of the box, not a placeholder. You can generate
your own instead (recommended before any real deployment, so you don't
share a key with every other clone of this repo) with:

    pip install py-vapid --break-system-packages
    vapid --gen  # writes private_key.pem / public_key.pem, prints both

...then set VAPID_PRIVATE_KEY_PEM and VAPID_PUBLIC_KEY env vars.

This delivers a real OS-level notification — even with the browser tab
or the whole browser closed — as long as the device is online and the
service worker (frontend/public/sw.js) is registered, exactly like a
mobile app's push notifications.
"""

import json
import os

from pywebpush import webpush
from py_vapid import Vapid01

from app.services import monitoring as monitoring_svc

# Working default keypair, generated for this project. Safe for local
# dev/demo use; generate your own (see docstring above) before any real
# multi-user deployment.
_DEFAULT_PRIVATE_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgJQnAppenmnmxdFpP
A/ljhsMUMIC2gvd+e2Aql518Q9uhRANCAAS6Tf+3IO5DBJB14kvYjP+BpAehvHIf
jXunE5hbTIMiAnsyvYKAc6cUMzdMx7kK69PUugUvTq3qPZGjsumdtq2u
-----END PRIVATE KEY-----"""
DEFAULT_VAPID_PUBLIC_KEY = "BLpN_7cg7kMEkHXiS9iM_4GkB6G8ch-Ne6cTmFtMgyICezK9goBzpxQzN0zHuQrr09S6BS9Oreo9kaOy6Z22ra4"

VAPID_PRIVATE_KEY_PEM = os.environ.get("VAPID_PRIVATE_KEY_PEM") or _DEFAULT_PRIVATE_KEY_PEM
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY") or DEFAULT_VAPID_PUBLIC_KEY
VAPID_CLAIM_EMAIL = os.environ.get("VAPID_CLAIM_EMAIL") or "mailto:admin@deliverysync.local"
# Deliberately `or` here, NOT os.environ.get(key, default) — an env var
# that's PRESENT but set to an empty string (e.g. `VAPID_PUBLIC_KEY=`
# left blank in a copied .env file, which is exactly what
# backend/.env.example has by default) is not the same as the var
# being absent, and os.environ.get()'s default only kicks in for the
# latter. With `.get(key, default)`, a blank .env line silently
# replaces this project's real, working checked-in keypair with an
# empty string — which is invalid for a push subscription and fails
# with a browser error like "applicationServerKey is not valid" the
# next time a customer tries to enable push notifications, even though
# nothing about push was ever meant to require configuration at all.
# `or` correctly treats blank-but-present the same as absent for every
# one of these three.

# pywebpush's own vapid_private_key parameter (when given a string, not
# a Vapid instance) is documented as either a raw base64 DER string or
# a FILE PATH — passed the full "-----BEGIN PRIVATE KEY-----\n...\n
# -----END PRIVATE KEY-----" PEM text directly, py_vapid's own
# from_string() does NOT strip those header/footer lines before
# base64-decoding, so it fails with a ValueError from deep inside the
# cryptography library on every single call (a real bug this project
# had — every previous push send silently crashed before this fix, but
# the test suite never exercised the code path since it only runs once
# a genuine PushSubscriptionDB row exists, which nothing before this
# session created). Building a real Vapid01 object once via
# Vapid01.from_pem() — which DOES correctly strip the PEM armor before
# decoding — and passing that object (not the raw string) to webpush()
# is what pywebpush's own isinstance(vapid_private_key, Vapid01) check
# exists to support; see docs/PROJECT_WORKFLOW.md for the full
# diagnosis.
_VAPID = Vapid01.from_pem(VAPID_PRIVATE_KEY_PEM.encode())


def send_web_push(subscription_info: dict, title: str, body: str, url: str = "/") -> bool:
    """
    Sends one real push notification to one subscribed browser.
    Returns True on success, False on failure (invalid/expired
    subscription, network error, etc.) — never raises, since a push
    failure must never break the status-update flow that triggered it.

    Catches broadly (not just WebPushException) on purpose: the actual
    HTTP POST to the browser's push service is a real network call
    (via `requests`, underneath pywebpush), so a transient DNS/
    connection failure raises `requests.exceptions.RequestException`,
    not `WebPushException` — narrowing the except clause to only the
    latter would violate this function's own "never raises" promise
    for that failure mode. Caught this gap while testing the VAPID-key
    fix below with a deliberately unreachable endpoint; see
    docs/PROJECT_WORKFLOW.md for the full diagnosis.
    """
    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps({"title": title, "body": body, "url": url}),
            vapid_private_key=_VAPID,
            vapid_claims={"sub": VAPID_CLAIM_EMAIL},
        )
        monitoring_svc.record_notification_sent("push", success=True)
        return True
    except Exception as e:
        print(f"Web push failed (subscription likely expired, or a network error): {e}")
        monitoring_svc.record_notification_sent("push", success=False)
        return False
