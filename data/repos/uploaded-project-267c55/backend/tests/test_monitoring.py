"""
Tests for Phase 18 — Monitoring & Reliability:
- Public health checks (no auth needed)
- Admin monitoring status: DB health, job heartbeats, websocket counts
- API metrics recorded across requests
- Notification metrics recorded on a real (dev-mode) email send
- Job heartbeat recording (via the service function directly, since
  waiting on a real scheduler tick in a test would be slow/flaky)
- Backup create/list/verify, including a rejected corrupt/missing file
  and a path-traversal filename rejected
- Admin-only access
- record_error() never raises even when logging itself fails
"""

from app.services import monitoring as monitoring_svc
from app.services import backup as backup_svc
from app.services import backup_scheduler as backup_scheduler_svc
from app.models.monitoring import JobHeartbeatDB
import os


# ---------- Public health ----------

def test_health_check_no_auth_needed(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_db_check_no_auth_needed(client):
    resp = client.get("/health/db")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert "latency_ms" in resp.json()


# ---------- Admin monitoring status ----------

def test_monitoring_status_admin_only(client, signed_up_admin, auth_headers):
    resp = client.get("/admin/monitoring/status", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["database"]["status"] == "ok"
    assert "websocket" in body
    assert "total_connections" in body["websocket"]

    invite_code = signed_up_admin["org_invite_code"]
    resp = client.post(
        "/auth/signup",
        json={
            "username": "monitoring_agent_noperm", "email": "monitoring_agent_noperm@example.com",
            "password": "correct-horse-battery", "role": "agent", "display_name": "Agent", "invite_code": invite_code,
        },
    )
    agent_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    resp = client.get("/admin/monitoring/status", headers=agent_headers)
    assert resp.status_code == 403


def test_monitoring_status_reflects_job_heartbeats(client, auth_headers, db_engine):
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        monitoring_svc.record_job_heartbeat(db, "reminder_scheduler", "success", 42)
    finally:
        db.close()

    resp = client.get("/admin/monitoring/status", headers=auth_headers)
    assert resp.status_code == 200
    job = next(j for j in resp.json()["background_jobs"] if j["job_name"] == "reminder_scheduler")
    assert job["last_status"] == "success"
    assert job["last_duration_ms"] == 42
    assert job["is_healthy"] is True
    assert resp.json()["all_jobs_healthy"] is True


def test_job_heartbeat_error_recorded_and_unhealthy_when_stale(db_engine):
    from sqlalchemy.orm import sessionmaker
    from datetime import datetime, timedelta
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        monitoring_svc.record_job_heartbeat(db, "webhook_scheduler", "error", 10, error_message="boom")
        row = db.query(JobHeartbeatDB).filter(JobHeartbeatDB.job_name == "webhook_scheduler").first()
        assert row.error_count == 1
        assert row.last_error_message == "boom"
        assert monitoring_svc.heartbeat_is_healthy(row) is True  # just ran, still within the stale threshold

        row.last_run_at = datetime.utcnow() - timedelta(minutes=monitoring_svc.JOB_STALE_THRESHOLD_MINUTES + 5)
        db.commit()
        assert monitoring_svc.heartbeat_is_healthy(row) is False
    finally:
        db.close()


def test_never_run_job_reports_unhealthy():
    row = JobHeartbeatDB(job_name="x", last_run_at=None, run_count=0, error_count=0)
    assert monitoring_svc.heartbeat_is_healthy(row) is False


# ---------- API & notification metrics ----------

def test_api_metrics_recorded_across_requests(client, auth_headers):
    client.get("/health")
    client.get("/health")
    resp = client.get("/admin/monitoring/api-metrics", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_requests"] > 0
    health_entry = next((e for e in body["slowest_endpoints"] if e["endpoint"] == "GET /health"), None)
    assert health_entry is not None
    assert health_entry["request_count"] >= 2


def test_notification_metrics_endpoint_shape(client, auth_headers):
    resp = client.get("/admin/monitoring/notification-metrics", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_notification_metrics_email_channel_increments(client, auth_headers):
    resp = client.post("/auth/me/change-password", json={"current_password": "correct-horse-battery", "new_password": "monitoring-test-pw-1"}, headers=auth_headers)
    assert resp.status_code == 200  # this sends a real security-alert email via services/email.py
    resp = client.get("/admin/monitoring/notification-metrics", headers=auth_headers)
    assert resp.json().get("email", {}).get("sent", 0) >= 1


# ---------- Backups ----------

def test_create_list_and_verify_backup(client, auth_headers):
    resp = client.post("/admin/monitoring/backups", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "success"
    filename = body["filename"]
    assert body["checksum_sha256"]

    resp = client.get("/admin/monitoring/backups", headers=auth_headers)
    assert resp.status_code == 200
    assert any(b["filename"] == filename for b in resp.json())

    resp = client.get(f"/admin/monitoring/backups/{filename}/verify", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert resp.json()["checksum_sha256"] == body["checksum_sha256"]


def test_verify_nonexistent_backup_returns_404(client, auth_headers):
    resp = client.get("/admin/monitoring/backups/does-not-exist.db/verify", headers=auth_headers)
    assert resp.status_code == 404


def test_verify_rejects_path_traversal_filename(client, auth_headers):
    resp = client.get("/admin/monitoring/backups/..%2F..%2Fetc%2Fpasswd/verify", headers=auth_headers)
    assert resp.status_code in (400, 404)  # rejected before ever touching the filesystem either way


def test_verify_backup_detects_corrupted_file(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_svc, "BACKUP_DIR", str(tmp_path))
    corrupt_path = tmp_path / "corrupt.db"
    corrupt_path.write_bytes(b"this is not a sqlite database")

    result = backup_svc.verify_backup("corrupt.db")
    assert result["status"] == "error"
    assert "not a valid sqlite" in result["message"].lower()


def test_backups_require_admin(client, signed_up_admin):
    invite_code = signed_up_admin["org_invite_code"]
    resp = client.post(
        "/auth/signup",
        json={
            "username": "monitoring_dispatcher_noperm", "email": "monitoring_dispatcher_noperm@example.com",
            "password": "correct-horse-battery", "role": "dispatcher", "display_name": "Dispatcher", "invite_code": invite_code,
        },
    )
    dispatcher_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    resp = client.post("/admin/monitoring/backups", headers=dispatcher_headers)
    assert resp.status_code == 403


# ---------- Postgres backups (real pg_dump, mocked here since this
# project's test suite runs against SQLite — see conftest.py) ----------

def test_postgres_backup_reports_clearly_when_pg_dump_missing(monkeypatch):
    monkeypatch.setattr(backup_svc, "IS_SQLITE", False)
    monkeypatch.setattr(backup_svc.shutil, "which", lambda _name: None)

    result = backup_svc.create_backup()
    assert result["status"] == "error"
    assert "pg_dump" in result["message"].lower()


def test_postgres_backup_runs_pg_dump_and_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_svc, "IS_SQLITE", False)
    monkeypatch.setattr(backup_svc, "BACKUP_DIR", str(tmp_path))
    monkeypatch.setattr(backup_svc.shutil, "which", lambda _name: "/usr/bin/pg_dump")

    def fake_run(cmd, capture_output, text, timeout):
        # Simulate pg_dump actually writing a dump file to the -f path.
        out_path = cmd[cmd.index("-f") + 1]
        with open(out_path, "w") as f:
            f.write("--\n-- PostgreSQL database dump\n--\n\nCREATE TABLE foo (id int);\n")

        class FakeResult:
            returncode = 0
            stderr = ""
        return FakeResult()

    monkeypatch.setattr(backup_svc.subprocess, "run", fake_run)

    result = backup_svc.create_backup()
    assert result["status"] == "success", result
    assert result["engine"] == "postgres"
    assert result["filename"].endswith(".sql")
    assert result["checksum_sha256"]

    verify_result = backup_svc.verify_backup(result["filename"])
    assert verify_result["status"] == "success"
    assert verify_result["engine"] == "postgres"

    listed = backup_svc.list_backups()
    assert any(b["filename"] == result["filename"] and b["engine"] == "postgres" for b in listed)


def test_postgres_backup_reports_pg_dump_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_svc, "IS_SQLITE", False)
    monkeypatch.setattr(backup_svc, "BACKUP_DIR", str(tmp_path))
    monkeypatch.setattr(backup_svc.shutil, "which", lambda _name: "/usr/bin/pg_dump")

    def fake_run(cmd, capture_output, text, timeout):
        class FakeResult:
            returncode = 1
            stderr = "pg_dump: error: connection to server failed"
        return FakeResult()

    monkeypatch.setattr(backup_svc.subprocess, "run", fake_run)

    result = backup_svc.create_backup()
    assert result["status"] == "error"
    assert "connection to server failed" in result["message"]


def test_postgres_backup_verify_rejects_non_dump_file(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_svc, "BACKUP_DIR", str(tmp_path))
    not_a_dump = tmp_path / "backup-fake.sql"
    not_a_dump.write_text("just some random text, not a real pg_dump")

    result = backup_svc.verify_backup("backup-fake.sql")
    assert result["status"] == "error"
    assert "pg_dump" in result["message"].lower()


# ---------- Backup retention policy ----------

def test_retention_keeps_newest_n_and_deletes_the_rest(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_svc, "BACKUP_DIR", str(tmp_path))
    # Filenames sort chronologically since the timestamp is embedded —
    # deliberately created out of order here to prove the function
    # sorts them itself rather than relying on creation order.
    names = [
        "backup-20260101T000000Z.db",
        "backup-20260103T000000Z.db",
        "backup-20260102T000000Z.db",
        "backup-20260104T000000Z.db",
        "backup-20260105T000000Z.db",
    ]
    for name in names:
        (tmp_path / name).write_text("fake backup content")

    deleted = backup_svc.apply_retention_policy(keep_count=3)

    assert set(deleted) == {"backup-20260101T000000Z.db", "backup-20260102T000000Z.db"}
    remaining = sorted(os.listdir(tmp_path))
    assert remaining == ["backup-20260103T000000Z.db", "backup-20260104T000000Z.db", "backup-20260105T000000Z.db"]


def test_retention_no_op_when_under_the_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_svc, "BACKUP_DIR", str(tmp_path))
    (tmp_path / "backup-20260101T000000Z.db").write_text("x")
    (tmp_path / "backup-20260102T000000Z.db").write_text("x")

    deleted = backup_svc.apply_retention_policy(keep_count=7)
    assert deleted == []
    assert len(os.listdir(tmp_path)) == 2


def test_retention_ignores_non_backup_files(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_svc, "BACKUP_DIR", str(tmp_path))
    (tmp_path / "backup-20260101T000000Z.db").write_text("x")
    (tmp_path / "readme.txt").write_text("not a backup")

    deleted = backup_svc.apply_retention_policy(keep_count=0)
    assert deleted == ["backup-20260101T000000Z.db"]
    assert os.listdir(tmp_path) == ["readme.txt"]


# ---------- Scheduled backup tick (services/backup_scheduler.py) ----------

def test_scheduled_backup_success_prunes_via_retention(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_svc, "BACKUP_DIR", str(tmp_path))
    monkeypatch.setattr(backup_scheduler_svc, "BACKUP_RETENTION_COUNT", 2)

    def fake_create_backup():
        # Simulate a real successful SQLite backup landing on disk.
        filename = f"backup-fake-{len(os.listdir(tmp_path))}.db"
        (tmp_path / filename).write_text("fake")
        return {"status": "success", "filename": filename, "size_bytes": 4, "checksum_sha256": "abc"}

    monkeypatch.setattr(backup_svc, "create_backup", fake_create_backup)

    # Pre-seed two older backups so retention has something to prune
    # once the new one lands.
    (tmp_path / "backup-20260101T000000Z.db").write_text("old")
    (tmp_path / "backup-20260102T000000Z.db").write_text("old")

    result = backup_scheduler_svc.run_scheduled_backup()
    assert result["status"] == "success"
    assert "deleted_by_retention" in result
    # 3 files existed (2 seeded + 1 new), keep_count=2 -> 1 pruned.
    assert len(result["deleted_by_retention"]) == 1
    assert len(os.listdir(tmp_path)) == 2


def test_scheduled_backup_failure_does_not_prune(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_svc, "BACKUP_DIR", str(tmp_path))
    monkeypatch.setattr(backup_svc, "create_backup", lambda: {"status": "error", "message": "disk full"})

    (tmp_path / "backup-20260101T000000Z.db").write_text("old")

    result = backup_scheduler_svc.run_scheduled_backup()
    assert result["status"] == "error"
    assert "deleted_by_retention" not in result
    # Nothing pruned on failure — the old backup is still the only real one.
    assert len(os.listdir(tmp_path)) == 1


def test_backup_scheduler_reads_interval_and_retention_from_env(monkeypatch):
    monkeypatch.setenv("BACKUP_INTERVAL_HOURS", "6")
    monkeypatch.setenv("BACKUP_RETENTION_COUNT", "3")
    import importlib
    reloaded = importlib.reload(backup_scheduler_svc)
    try:
        assert reloaded.BACKUP_INTERVAL_SECONDS == 6 * 3600
        assert reloaded.BACKUP_RETENTION_COUNT == 3
    finally:
        # Restore module-level state for any test that runs after this
        # one and imports backup_scheduler_svc fresh from sys.modules.
        monkeypatch.delenv("BACKUP_INTERVAL_HOURS", raising=False)
        monkeypatch.delenv("BACKUP_RETENTION_COUNT", raising=False)
        importlib.reload(backup_scheduler_svc)


def test_backup_scheduler_not_started_during_tests():
    # main.py's _launch_backup_scheduler checks TESTING itself and
    # returns early — this asserts the guard's precondition actually
    # holds throughout this test run (conftest.py sets this before any
    # app import happens), rather than re-testing FastAPI's own
    # startup-event mechanism.
    assert os.environ.get("TESTING") == "1"


# ---------- Error tracking ----------

def test_record_error_never_raises_on_bad_db(db_engine):
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=db_engine)
    db = Session()
    db.close()  # a closed session — record_error must swallow the resulting failure, not propagate it
    try:
        monitoring_svc.record_error(db, None, "GET", "/some/path", ValueError("boom"))
    except Exception as e:  # pragma: no cover - this is exactly what must NOT happen
        assert False, f"record_error raised: {e}"
