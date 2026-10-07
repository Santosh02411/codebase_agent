"""
Real push notifications to the mobile agent app (mobile/) — the mobile
equivalent of services/push.py's Web Push for the web app. Needs no
paid third-party account and no API key: Expo runs a free push
notification gateway (https://exp.host) that accepts a plain HTTP POST
and fans it out to Apple's (APNs) or Google's (FCM) own push services
on Expo's own developer credentials, not this project's — that's the
whole point of building on Expo rather than integrating APNs/FCM
directly, and it's why this integration needs zero configuration to
work, same "real integration, zero required setup" story as every
other notification channel in this project.

Delivers a real OS-level notification — even with the mobile app fully
closed — as long as the device is online and has previously registered
its Expo push token (see routes/users.py's POST /me/expo-push-token,
called by the mobile app once notification permission is granted; see
mobile/src/services/pushNotifications.js).
"""

import requests

from app.services import monitoring as monitoring_svc

EXPO_PUSH_API_URL = "https://exp.host/--/api/v2/push/send"
REQUEST_TIMEOUT_SECONDS = 10


def send_expo_push(token: str, title: str, body: str, data: dict = None) -> bool:
    """
    Sends one real push notification to one registered Expo push
    token. Returns True on success, False on failure (invalid/expired
    token, network error, etc.) — never raises, matching
    services/push.py's send_web_push()'s exact same "a notification
    failure must never break the status-update flow that triggered it"
    contract. Recorded under its own "expo_push" channel in
    services/monitoring.py's notification metrics — separate from Web
    Push's "push" channel, so /admin/monitoring can distinguish which
    delivery mechanism is actually succeeding/failing.
    """
    try:
        response = requests.post(
            EXPO_PUSH_API_URL,
            json={
                "to": token,
                "title": title,
                "body": body,
                "data": data or {},
                "sound": "default",
            },
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            print(f"Expo push failed: HTTP {response.status_code} — {response.text[:300]}")
            monitoring_svc.record_notification_sent("expo_push", success=False)
            return False

        # Expo's own API returns 200 even for a token-level rejection
        # (e.g. "DeviceNotRegistered" for an uninstalled app) — the
        # real success/failure signal is inside the response body's
        # per-ticket status, not the HTTP status code alone.
        result = response.json().get("data", {})
        status = result.get("status")
        if status != "ok":
            print(f"Expo push rejected: {result.get('message', status)}")
            monitoring_svc.record_notification_sent("expo_push", success=False)
            return False

        monitoring_svc.record_notification_sent("expo_push", success=True)
        return True
    except requests.RequestException as e:
        print(f"Expo push failed (network error): {e}")
        monitoring_svc.record_notification_sent("expo_push", success=False)
        return False
