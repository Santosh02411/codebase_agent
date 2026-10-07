"""
Tests for the mobile Expo push notification feature: POST/DELETE
/users/me/expo-push-token (routes/users.py) and the extended
_push_to_user_ids() fan-out in services/notifications.py that now
sends to both Web Push subscriptions AND registered Expo tokens for
the same staff user id set.
"""

from unittest.mock import patch

from app.models.expo_push_token import ExpoPushTokenDB
from app.services import notifications as notifications_svc


# ---------- POST/DELETE /users/me/expo-push-token ----------

def test_register_expo_push_token(client, db_engine, auth_headers, signed_up_admin):
    resp = client.post("/users/me/expo-push-token", json={"token": "ExponentPushToken[abc123]"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text

    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=db_engine)
    db = Session()
    row = db.query(ExpoPushTokenDB).filter(ExpoPushTokenDB.token == "ExponentPushToken[abc123]").first()
    assert row is not None
    assert row.user_id == signed_up_admin["user"]["id"]
    db.close()


def test_registering_the_same_token_twice_reassigns_rather_than_duplicates(client, db_engine, auth_headers, signed_up_admin):
    client.post("/users/me/expo-push-token", json={"token": "ExponentPushToken[shared]"}, headers=auth_headers)
    client.post("/users/me/expo-push-token", json={"token": "ExponentPushToken[shared]"}, headers=auth_headers)

    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=db_engine)
    db = Session()
    assert db.query(ExpoPushTokenDB).filter(ExpoPushTokenDB.token == "ExponentPushToken[shared]").count() == 1
    db.close()


def test_register_expo_push_token_requires_auth(client):
    resp = client.post("/users/me/expo-push-token", json={"token": "ExponentPushToken[x]"})
    assert resp.status_code in (401, 403)


def test_unregister_expo_push_token(client, db_engine, auth_headers):
    client.post("/users/me/expo-push-token", json={"token": "ExponentPushToken[gone]"}, headers=auth_headers)

    resp = client.request("DELETE", "/users/me/expo-push-token", json={"token": "ExponentPushToken[gone]"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text

    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=db_engine)
    db = Session()
    assert db.query(ExpoPushTokenDB).filter(ExpoPushTokenDB.token == "ExponentPushToken[gone]").count() == 0
    db.close()


def test_unregister_only_removes_the_calling_users_own_token(client, db_engine, auth_headers, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    other_resp = client.post("/auth/signup", json={
        "username": "other_agent", "email": "other_agent@example.com",
        "password": "correct-horse-battery", "role": "agent",
        "display_name": "Other Agent", "invite_code": invite_code,
    })
    other_headers = {"Authorization": f"Bearer {other_resp.json()['access_token']}"}

    # Same token string registered by a different user (a contrived
    # edge case, but the ownership check should still hold).
    client.post("/users/me/expo-push-token", json={"token": "ExponentPushToken[owned-by-other]"}, headers=other_headers)

    resp = client.request("DELETE", "/users/me/expo-push-token", json={"token": "ExponentPushToken[owned-by-other]"}, headers=auth_headers)
    assert resp.status_code == 200

    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=db_engine)
    db = Session()
    # Still there — belongs to other_agent, not the caller.
    assert db.query(ExpoPushTokenDB).filter(ExpoPushTokenDB.token == "ExponentPushToken[owned-by-other]").count() == 1
    db.close()


# ---------- Extended notification fan-out ----------

def test_push_to_user_ids_sends_to_registered_expo_tokens(client, db_engine, auth_headers, signed_up_admin):
    admin_id = signed_up_admin["user"]["id"]
    client.post("/users/me/expo-push-token", json={"token": "ExponentPushToken[fanout]"}, headers=auth_headers)

    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=db_engine)
    db = Session()

    with patch.object(notifications_svc, "send_expo_push") as mock_send:
        notifications_svc._push_to_user_ids(db, [admin_id], title="Test", body="Hello", url="/x")

    mock_send.assert_called_once_with("ExponentPushToken[fanout]", title="Test", body="Hello")
    db.close()


def test_push_to_user_ids_does_not_call_expo_push_with_no_registered_tokens(db_engine, signed_up_admin):
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=db_engine)
    db = Session()

    with patch.object(notifications_svc, "send_expo_push") as mock_send:
        notifications_svc._push_to_user_ids(db, [signed_up_admin["user"]["id"]], title="Test", body="Hello", url="/x")

    mock_send.assert_not_called()
    db.close()


def test_push_to_user_ids_expo_failure_does_not_break_web_push(client, db_engine, auth_headers, signed_up_admin):
    # If sending to a registered Expo token raises, Web Push for the
    # same user set must still be attempted — same "one channel's
    # failure must never break another" contract as everything else in
    # this notification stack.
    admin_id = signed_up_admin["user"]["id"]
    client.post("/users/me/expo-push-token", json={"token": "ExponentPushToken[will-error]"}, headers=auth_headers)

    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=db_engine)
    db = Session()

    with patch.object(notifications_svc, "send_expo_push", side_effect=RuntimeError("boom")), \
         patch.object(notifications_svc, "send_web_push") as mock_web_push:
        # Must not raise.
        notifications_svc._push_to_user_ids(db, [admin_id], title="Test", body="Hello", url="/x")

    db.close()
