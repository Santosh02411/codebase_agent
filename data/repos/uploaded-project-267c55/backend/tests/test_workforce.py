"""
Tests for Group 3 — workforce management: shifts (roster), attendance
(clock in/out), leave requests (approval workflow), and earnings
(computed pay statements).
"""

import uuid
from datetime import date, datetime, timedelta

from app.models.delivery import DeliveryRecordDB, DeliveryStatus
from sqlalchemy.orm import sessionmaker


def _session_for(db_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=db_engine)()


def _signup_agent(client, invite_code, username):
    resp = client.post(
        "/auth/signup",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "correct-horse-battery",
            "role": "agent",
            "display_name": username.replace("_", " ").title(),
            "invite_code": invite_code,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["user"]["id"], {"Authorization": f"Bearer {body['access_token']}"}


def _make_delivered_attempt(db_engine, org_id, agent_id, outcome="delivered", attempted_at=None):
    db = _session_for(db_engine)
    try:
        from app.models.delivery_attempt import DeliveryAttemptDB
        entry = DeliveryAttemptDB(
            id=str(uuid.uuid4()),
            delivery_id=str(uuid.uuid4()),
            org_id=org_id,
            agent_id=agent_id,
            attempt_number=1,
            outcome=outcome,
            attempted_at=attempted_at or datetime.utcnow(),
        )
        db.add(entry)
        db.commit()
    finally:
        db.close()


# ---------- Shifts ----------

def test_dispatcher_can_create_and_list_shifts(client, auth_headers, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "shift_agent")

    resp = client.post(
        "/workforce/shifts",
        json={"user_id": agent_id, "shift_date": "2026-09-01", "start_time": "09:00:00", "end_time": "17:00:00"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    shift = resp.json()
    assert shift["status"] == "scheduled"

    resp = client.get("/workforce/shifts", headers=auth_headers)
    assert resp.status_code == 200
    assert any(s["id"] == shift["id"] for s in resp.json())

    resp = client.get("/workforce/shifts/mine", headers=agent_headers)
    assert resp.status_code == 200
    assert any(s["id"] == shift["id"] for s in resp.json())


def test_shift_end_before_start_is_rejected(client, auth_headers, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "bad_shift_agent")

    resp = client.post(
        "/workforce/shifts",
        json={"user_id": agent_id, "shift_date": "2026-09-01", "start_time": "17:00:00", "end_time": "09:00:00"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_agent_cannot_create_shifts(client, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "no_perm_agent")

    resp = client.post(
        "/workforce/shifts",
        json={"user_id": agent_id, "shift_date": "2026-09-01", "start_time": "09:00:00", "end_time": "17:00:00"},
        headers=agent_headers,
    )
    assert resp.status_code == 403


def test_dispatcher_can_update_and_delete_shift(client, auth_headers, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "editable_shift_agent")

    resp = client.post(
        "/workforce/shifts",
        json={"user_id": agent_id, "shift_date": "2026-09-01", "start_time": "09:00:00", "end_time": "17:00:00"},
        headers=auth_headers,
    )
    shift_id = resp.json()["id"]

    resp = client.patch(f"/workforce/shifts/{shift_id}", json={"status": "cancelled"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelled"

    resp = client.delete(f"/workforce/shifts/{shift_id}", headers=auth_headers)
    assert resp.status_code == 200
    resp = client.get("/workforce/shifts", headers=auth_headers)
    assert not any(s["id"] == shift_id for s in resp.json())


def test_shifts_filter_by_date_range(client, auth_headers, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "range_shift_agent")

    client.post("/workforce/shifts", json={"user_id": agent_id, "shift_date": "2026-09-01", "start_time": "09:00:00", "end_time": "17:00:00"}, headers=auth_headers)
    client.post("/workforce/shifts", json={"user_id": agent_id, "shift_date": "2026-09-15", "start_time": "09:00:00", "end_time": "17:00:00"}, headers=auth_headers)

    resp = client.get("/workforce/shifts", params={"date_from": "2026-09-10", "date_to": "2026-09-20"}, headers=auth_headers)
    assert resp.status_code == 200
    dates = [s["shift_date"] for s in resp.json()]
    assert dates == ["2026-09-15"]


# ---------- Attendance ----------

def test_agent_can_clock_in_and_out(client, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "clock_agent")

    resp = client.post("/workforce/attendance/clock-in", json={"note": "starting shift"}, headers=agent_headers)
    assert resp.status_code == 200, resp.text
    record = resp.json()
    assert record["clock_out_at"] is None
    assert record["is_unscheduled"] is True

    resp = client.post("/workforce/attendance/clock-out", json={"note": "done"}, headers=agent_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["clock_out_at"] is not None

    resp = client.get("/workforce/attendance/mine", headers=agent_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_cannot_clock_in_twice(client, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    _, agent_headers = _signup_agent(client, invite_code, "double_clock_agent")

    client.post("/workforce/attendance/clock-in", json={}, headers=agent_headers)
    resp = client.post("/workforce/attendance/clock-in", json={}, headers=agent_headers)
    assert resp.status_code == 400


def test_cannot_clock_out_without_clocking_in(client, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    _, agent_headers = _signup_agent(client, invite_code, "no_clockin_agent")

    resp = client.post("/workforce/attendance/clock-out", json={}, headers=agent_headers)
    assert resp.status_code == 400


def test_clock_in_against_own_shift_marks_it_scheduled_not_unscheduled_and_completes_it(client, auth_headers, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "shift_clock_agent")

    resp = client.post(
        "/workforce/shifts",
        json={"user_id": agent_id, "shift_date": str(date.today()), "start_time": "09:00:00", "end_time": "17:00:00"},
        headers=auth_headers,
    )
    shift_id = resp.json()["id"]

    resp = client.post("/workforce/attendance/clock-in", json={"shift_id": shift_id}, headers=agent_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_unscheduled"] is False

    client.post("/workforce/attendance/clock-out", json={}, headers=agent_headers)

    resp = client.get("/workforce/shifts/mine", headers=agent_headers)
    matching = [s for s in resp.json() if s["id"] == shift_id][0]
    assert matching["status"] == "completed"


def test_dispatcher_can_view_org_attendance(client, auth_headers, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    _, agent_headers = _signup_agent(client, invite_code, "visible_attendance_agent")
    client.post("/workforce/attendance/clock-in", json={}, headers=agent_headers)

    resp = client.get("/workforce/attendance", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


# ---------- Leave requests ----------

def test_leave_request_lifecycle_approve(client, auth_headers, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    _, agent_headers = _signup_agent(client, invite_code, "leave_agent")

    resp = client.post(
        "/workforce/leave-requests",
        json={"leave_type": "vacation", "start_date": "2026-10-01", "end_date": "2026-10-05", "reason": "Trip"},
        headers=agent_headers,
    )
    assert resp.status_code == 200, resp.text
    req_id = resp.json()["id"]
    assert resp.json()["status"] == "pending"

    resp = client.get("/workforce/leave-requests/mine", headers=agent_headers)
    assert any(r["id"] == req_id for r in resp.json())

    resp = client.get("/workforce/leave-requests", params={"status": "pending"}, headers=auth_headers)
    assert any(r["id"] == req_id for r in resp.json())

    resp = client.post(f"/workforce/leave-requests/{req_id}/approve", json={"review_note": "Enjoy!"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"
    assert resp.json()["review_note"] == "Enjoy!"


def test_leave_request_reject_and_double_review_rejected(client, auth_headers, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    _, agent_headers = _signup_agent(client, invite_code, "leave_reject_agent")

    resp = client.post(
        "/workforce/leave-requests",
        json={"leave_type": "sick", "start_date": "2026-10-01", "end_date": "2026-10-01"},
        headers=agent_headers,
    )
    req_id = resp.json()["id"]

    resp = client.post(f"/workforce/leave-requests/{req_id}/reject", json={"review_note": "Too short notice"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"

    resp = client.post(f"/workforce/leave-requests/{req_id}/approve", json={}, headers=auth_headers)
    assert resp.status_code == 400


def test_leave_request_end_before_start_rejected(client, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    _, agent_headers = _signup_agent(client, invite_code, "leave_baddate_agent")

    resp = client.post(
        "/workforce/leave-requests",
        json={"leave_type": "personal", "start_date": "2026-10-05", "end_date": "2026-10-01"},
        headers=agent_headers,
    )
    assert resp.status_code == 400


def test_agent_can_cancel_own_pending_leave_request(client, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    _, agent_headers = _signup_agent(client, invite_code, "leave_cancel_agent")

    resp = client.post(
        "/workforce/leave-requests",
        json={"leave_type": "unpaid", "start_date": "2026-11-01", "end_date": "2026-11-02"},
        headers=agent_headers,
    )
    req_id = resp.json()["id"]

    resp = client.post(f"/workforce/leave-requests/{req_id}/cancel", headers=agent_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_non_dispatcher_cannot_approve_leave(client, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    _, agent_headers = _signup_agent(client, invite_code, "leave_noperm_agent")
    _, agent2_headers = _signup_agent(client, invite_code, "leave_noperm_agent2")

    resp = client.post(
        "/workforce/leave-requests",
        json={"leave_type": "personal", "start_date": "2026-10-01", "end_date": "2026-10-01"},
        headers=agent_headers,
    )
    req_id = resp.json()["id"]

    resp = client.post(f"/workforce/leave-requests/{req_id}/approve", json={}, headers=agent2_headers)
    assert resp.status_code == 403


# ---------- Pay rates + earnings ----------

def test_admin_can_set_pay_rates(client, auth_headers, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "payrate_agent")

    resp = client.patch(f"/workforce/pay-rate/{agent_id}", json={"hourly_rate": 15.0, "per_delivery_rate": 2.5}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["hourly_rate"] == 15.0
    assert resp.json()["per_delivery_rate"] == 2.5

    resp = client.patch(f"/workforce/pay-rate/{agent_id}", json={"hourly_rate": None}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["hourly_rate"] is None
    assert resp.json()["per_delivery_rate"] == 2.5  # untouched since omitted


def test_earnings_generation_combines_hours_and_deliveries(client, db_engine, auth_headers, signed_up_admin):
    org_id = signed_up_admin["user"]["org_id"]
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, agent_headers = _signup_agent(client, invite_code, "earnings_agent")

    client.patch(f"/workforce/pay-rate/{agent_id}", json={"hourly_rate": 10.0, "per_delivery_rate": 3.0}, headers=auth_headers)

    period_start = date.today() - timedelta(days=1)
    period_end = date.today() + timedelta(days=1)
    mid = datetime.combine(date.today(), datetime.min.time()) + timedelta(hours=12)

    db = _session_for(db_engine)
    try:
        from app.models.attendance import AttendanceDB
        att = AttendanceDB(
            id=str(uuid.uuid4()), org_id=org_id, user_id=agent_id,
            clock_in_at=mid, clock_out_at=mid + timedelta(hours=4),
        )
        db.add(att)
        db.commit()
    finally:
        db.close()

    _make_delivered_attempt(db_engine, org_id, agent_id, outcome="delivered", attempted_at=mid)
    _make_delivered_attempt(db_engine, org_id, agent_id, outcome="partial_delivery", attempted_at=mid)
    _make_delivered_attempt(db_engine, org_id, agent_id, outcome="failed_attempt", attempted_at=mid)  # should NOT count

    resp = client.post(
        "/workforce/earnings/generate",
        json={"user_id": agent_id, "period_start": period_start.isoformat(), "period_end": period_end.isoformat()},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    statements = resp.json()
    assert len(statements) == 1
    stmt = statements[0]
    assert stmt["hours_worked"] == 4.0
    assert stmt["base_pay"] == 40.0
    assert stmt["deliveries_completed"] == 2
    assert stmt["delivery_pay"] == 6.0
    assert stmt["total_pay"] == 46.0
    assert stmt["status"] == "draft"

    resp = client.get("/workforce/earnings/mine", headers=agent_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_earnings_generate_for_whole_org_when_no_user_specified(client, auth_headers, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    _signup_agent(client, invite_code, "org_wide_agent_1")
    _signup_agent(client, invite_code, "org_wide_agent_2")

    resp = client.post(
        "/workforce/earnings/generate",
        json={"period_start": "2026-01-01", "period_end": "2026-01-31"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    # admin + 2 agents == at least 3 statements
    assert len(resp.json()) >= 3


def test_earnings_finalize_and_mark_paid_flow(client, auth_headers, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "finalize_agent")

    resp = client.post(
        "/workforce/earnings/generate",
        json={"user_id": agent_id, "period_start": "2026-01-01", "period_end": "2026-01-31"},
        headers=auth_headers,
    )
    statement_id = resp.json()[0]["id"]

    # Can't mark paid before finalizing
    resp = client.post(f"/workforce/earnings/{statement_id}/mark-paid", headers=auth_headers)
    assert resp.status_code == 400

    resp = client.post(f"/workforce/earnings/{statement_id}/finalize", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "finalized"

    resp = client.post(f"/workforce/earnings/{statement_id}/mark-paid", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "paid"
    assert resp.json()["paid_at"] is not None


def test_regenerating_a_paid_statement_leaves_it_unchanged(client, auth_headers, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    agent_id, _ = _signup_agent(client, invite_code, "paid_immutable_agent")
    client.patch(f"/workforce/pay-rate/{agent_id}", json={"hourly_rate": 10.0}, headers=auth_headers)

    resp = client.post(
        "/workforce/earnings/generate",
        json={"user_id": agent_id, "period_start": "2026-02-01", "period_end": "2026-02-28"},
        headers=auth_headers,
    )
    statement_id = resp.json()[0]["id"]
    client.post(f"/workforce/earnings/{statement_id}/finalize", headers=auth_headers)
    client.post(f"/workforce/earnings/{statement_id}/mark-paid", headers=auth_headers)

    # Bump the rate and regenerate for the same period — paid statement should be untouched.
    client.patch(f"/workforce/pay-rate/{agent_id}", json={"hourly_rate": 999.0}, headers=auth_headers)
    resp = client.post(
        "/workforce/earnings/generate",
        json={"user_id": agent_id, "period_start": "2026-02-01", "period_end": "2026-02-28"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    regenerated = resp.json()[0]
    assert regenerated["id"] == statement_id
    assert regenerated["status"] == "paid"
    assert regenerated["hourly_rate"] == 10.0  # unchanged, not 999


def test_non_dispatcher_cannot_generate_or_view_org_earnings(client, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    _, agent_headers = _signup_agent(client, invite_code, "earnings_noperm_agent")

    resp = client.post(
        "/workforce/earnings/generate",
        json={"period_start": "2026-01-01", "period_end": "2026-01-31"},
        headers=agent_headers,
    )
    assert resp.status_code == 403

    resp = client.get("/workforce/earnings", headers=agent_headers)
    assert resp.status_code == 403
