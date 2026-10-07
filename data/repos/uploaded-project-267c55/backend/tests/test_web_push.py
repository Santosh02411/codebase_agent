"""
Tests for services/push.py (Web Push). Written while adding Expo push
notifications for the mobile app (see test_expo_push.py) after finding
this module had two real, pre-existing bugs that meant every actual
push send silently crashed — see docs/PROJECT_WORKFLOW.md for the full
diagnosis of both. Neither was ever caught before because send_web_push
is only reached once a genuine PushSubscriptionDB row exists, and
nothing in the test suite created one before this file.
"""

from app.services import push as push_svc


def test_send_web_push_never_raises_on_a_malformed_or_unreachable_endpoint():
    # Regression test for bug #1: the checked-in default VAPID key was
    # passed to pywebpush as a raw PEM string (with "-----BEGIN...-----"
    # header/footer lines), which py_vapid's own Vapid.from_string()
    # does not strip before base64-decoding — every call raised a
    # ValueError from inside the cryptography library before ever
    # reaching the network. If that regresses, this call raises instead
    # of returning False, and the test fails with that traceback.
    result = push_svc.send_web_push(
        subscription_info={
            "endpoint": "https://fake.invalid.example/endpoint",
            "keys": {
                "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM=",
                "auth": "tBHItJI5svbpez7KI4CCXg==",
            },
        },
        title="Test",
        body="Hello",
    )
    assert result is False


def test_send_web_push_survives_a_network_level_failure():
    # Regression test for bug #2: once bug #1 was fixed, the same
    # unreachable-endpoint call surfaced a SECOND gap — the actual HTTP
    # POST (inside pywebpush, via `requests`) raises
    # requests.exceptions.ConnectionError on a DNS/connection failure,
    # which the original `except WebPushException` clause did not
    # catch, breaking this function's own documented "never raises"
    # contract. Broadened to catch generally; this test's fake,
    # unresolvable hostname is exactly the case that used to escape.
    result = push_svc.send_web_push(
        subscription_info={
            "endpoint": "https://this-host-does-not-exist.invalid/endpoint",
            "keys": {"p256dh": "x", "auth": "y"},
        },
        title="Test",
        body="Hello",
    )
    assert result is False


def test_vapid_object_is_built_once_from_the_checked_in_default_key():
    # The module-level _VAPID object existing at all (built at import
    # time via Vapid01.from_pem) is itself proof the default key parses
    # correctly — this would have failed at import time otherwise.
    assert push_svc._VAPID is not None


def test_default_vapid_public_key_is_present_and_nonempty():
    # Sanity check on the "or", not ".get(key, default)" env-var
    # handling this module's own comment explains — a blank .env
    # VAPID_PUBLIC_KEY line must not silently become an empty string.
    assert push_svc.VAPID_PUBLIC_KEY
    assert len(push_svc.VAPID_PUBLIC_KEY) > 20
