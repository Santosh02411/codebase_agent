"""
Tests for services/captcha.py, and confirmation that signup/forgot-
password work with NO captcha_token when RECAPTCHA_SECRET_KEY isn't
configured (the default state in tests, matching the no-op-by-default
design shared with this project's other optional integrations).

The "actually configured" branch is tested directly against
verify_captcha() with monkeypatched module state and a mocked HTTP
call, rather than end-to-end through an endpoint — spinning up a real
Google reCAPTCHA site for CI would defeat the purpose of a fast,
offline test suite, and the endpoints' own logic (call verify_captcha,
400 on failure) is trivial enough that unit-testing the service
function directly gives equivalent coverage.
"""

import app.services.captcha as captcha_module


def test_verify_captcha_is_noop_when_unconfigured():
    assert captcha_module.IS_CONFIGURED is False
    # Passes regardless of the token — including a missing one.
    assert captcha_module.verify_captcha(None) is True
    assert captcha_module.verify_captcha("") is True
    assert captcha_module.verify_captcha("anything") is True


def test_signup_and_forgot_password_work_without_captcha_token_when_unconfigured(client, admin_signup_payload):
    # No captcha_token in the payload at all — same as every other
    # existing test in this suite, confirming the no-op default never
    # broke normal signup.
    assert "captcha_token" not in admin_signup_payload
    resp = client.post("/auth/signup", json=admin_signup_payload)
    assert resp.status_code == 200, resp.text

    resp = client.post("/auth/forgot-password", json={"email": admin_signup_payload["email"]})
    assert resp.status_code == 200, resp.text


def test_verify_captcha_rejects_missing_token_when_configured(monkeypatch):
    monkeypatch.setattr(captcha_module, "IS_CONFIGURED", True)
    monkeypatch.setattr(captcha_module, "RECAPTCHA_SECRET_KEY", "fake-secret")
    assert captcha_module.verify_captcha(None) is False
    assert captcha_module.verify_captcha("") is False


def test_verify_captcha_success_when_configured(monkeypatch):
    monkeypatch.setattr(captcha_module, "IS_CONFIGURED", True)
    monkeypatch.setattr(captcha_module, "RECAPTCHA_SECRET_KEY", "fake-secret")

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"success": True}

    monkeypatch.setattr(captcha_module.requests, "post", lambda *a, **k: FakeResponse())

    assert captcha_module.verify_captcha("some-widget-token") is True


def test_verify_captcha_failure_when_configured(monkeypatch):
    monkeypatch.setattr(captcha_module, "IS_CONFIGURED", True)
    monkeypatch.setattr(captcha_module, "RECAPTCHA_SECRET_KEY", "fake-secret")

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"success": False, "error-codes": ["invalid-input-response"]}

    monkeypatch.setattr(captcha_module.requests, "post", lambda *a, **k: FakeResponse())

    assert captcha_module.verify_captcha("bad-token") is False


def test_verify_captcha_treats_network_failure_as_rejected(monkeypatch):
    import requests

    monkeypatch.setattr(captcha_module, "IS_CONFIGURED", True)
    monkeypatch.setattr(captcha_module, "RECAPTCHA_SECRET_KEY", "fake-secret")

    def _raise(*a, **k):
        raise requests.RequestException("network down")

    monkeypatch.setattr(captcha_module.requests, "post", _raise)

    assert captcha_module.verify_captcha("some-token") is False
