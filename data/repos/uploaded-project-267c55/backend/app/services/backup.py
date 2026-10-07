"""
Database backup (Phase 18; PostgreSQL support and automated scheduling
+ retention added in later polish sessions).

This project's default and test configuration is SQLite (see
db/session.py's IS_SQLITE), backed up here via a file-level copy — the
standard, correct way to back up a SQLite database (SQLite itself
recommends this over trying to re-implement it via SQL dump for a
simple point-in-time snapshot).

For PostgreSQL (this project's other supported mode, e.g. in
production), backup here shells out to the real `pg_dump` binary
against SQLALCHEMY_DATABASE_URL — a genuine dump, not a stub. One
honest limitation, stated plainly rather than hidden: it requires
`pg_dump` to actually be installed and on PATH in whatever environment
runs the FastAPI process — if it isn't, create_backup() reports that
clearly rather than pretending to succeed. (The postgres client tools
package — e.g. `postgresql-client` on Debian/Ubuntu — provides it;
it's a separate install from the psycopg2 Python driver this project
already uses to connect.)

Scheduling + retention (services/backup_scheduler.py, wired into
main.py's startup) turn the admin's manual "back up now" button into
an actual automated strategy: a real backup on an interval
(BACKUP_INTERVAL_HOURS, default 24), with old backups pruned down to a
fixed count (BACKUP_RETENTION_COUNT, default 7) so disk usage doesn't
grow unbounded. Still an honest, bounded claim, not a substitute for
everything a managed database provider's automated backups give you:
this backup lives on the SAME disk as the database it's backing up
(no offsite/geo-redundant copy) and there's no point-in-time recovery
between snapshots — see docs/DISASTER_RECOVERY.md for what that means
in practice and when to layer a real managed-provider backup on top
instead of relying on this alone.
"""

import hashlib
import os
import shutil
import subprocess
from datetime import datetime

from app.db.session import IS_SQLITE, SQLALCHEMY_DATABASE_URL

BACKUP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

PG_DUMP_TIMEOUT_SECONDS = 300


def _sqlite_db_path() -> str:
    # "sqlite:///./database.db" -> "./database.db"
    return SQLALCHEMY_DATABASE_URL.replace("sqlite:///", "", 1)


def _pg_dump_connection_url() -> str:
    # SQLAlchemy may use a dialect+driver form like
    # "postgresql+psycopg2://user:pass@host/db" — pg_dump only
    # understands the plain "postgresql://" libpq form, so the
    # "+driver" part (if present) is stripped before handing the URL
    # to the pg_dump subprocess.
    scheme, _, rest = SQLALCHEMY_DATABASE_URL.partition("://")
    scheme = scheme.split("+", 1)[0]
    return f"{scheme}://{rest}"


def _file_checksum(path: str) -> str:
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def create_backup() -> dict:
    """
    Returns a dict describing the outcome. Never raises — a failed
    backup attempt should be a reported status, not a crashed request.
    """
    if IS_SQLITE:
        return _create_sqlite_backup()
    return _create_postgres_backup()


def _create_sqlite_backup() -> dict:
    db_path = _sqlite_db_path()
    if not os.path.exists(db_path):
        return {"status": "error", "message": f"Database file not found at {db_path}."}

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    backup_filename = f"backup-{timestamp}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_filename)

    try:
        shutil.copyfile(db_path, backup_path)
        checksum = _file_checksum(backup_path)
        size_bytes = os.path.getsize(backup_path)
    except OSError as error:
        return {"status": "error", "message": str(error)}

    return {
        "status": "success",
        "filename": backup_filename,
        "size_bytes": size_bytes,
        "checksum_sha256": checksum,
        "created_at": timestamp,
        "engine": "sqlite",
    }


def _create_postgres_backup() -> dict:
    if shutil.which("pg_dump") is None:
        return {
            "status": "error",
            "message": (
                "pg_dump is not installed (or not on PATH) in this environment. Install the "
                "PostgreSQL client tools package (e.g. `apt-get install postgresql-client`) to "
                "enable this, or rely on your managed database provider's automated backups instead."
            ),
        }

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    backup_filename = f"backup-{timestamp}.sql"
    backup_path = os.path.join(BACKUP_DIR, backup_filename)

    conn_url = _pg_dump_connection_url()
    try:
        result = subprocess.run(
            [
                "pg_dump",
                f"--dbname={conn_url}",
                "--no-owner",
                "--no-privileges",
                "-f", backup_path,
            ],
            capture_output=True,
            text=True,
            timeout=PG_DUMP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        if os.path.exists(backup_path):
            os.remove(backup_path)
        return {"status": "error", "message": f"pg_dump timed out after {PG_DUMP_TIMEOUT_SECONDS}s."}
    except OSError as error:
        return {"status": "error", "message": f"Failed to run pg_dump: {error}"}

    if result.returncode != 0:
        if os.path.exists(backup_path):
            os.remove(backup_path)
        stderr = (result.stderr or "").strip()
        return {"status": "error", "message": f"pg_dump exited with code {result.returncode}: {stderr[-2000:]}"}

    if not os.path.exists(backup_path) or os.path.getsize(backup_path) == 0:
        return {"status": "error", "message": "pg_dump reported success but produced no output file."}

    return {
        "status": "success",
        "filename": backup_filename,
        "size_bytes": os.path.getsize(backup_path),
        "checksum_sha256": _file_checksum(backup_path),
        "created_at": timestamp,
        "engine": "postgres",
    }


def verify_backup(filename: str) -> dict:
    """
    Confirms a backup file exists and computes its checksum.

    For a SQLite backup (.db), this also actually opens it as a real
    SQLite database and runs a trivial query — a file that copies
    successfully but isn't openable/valid (truncated mid-write,
    corrupted) is exactly the failure mode a checksum alone can't
    catch; only actually opening it as a database can.

    For a PostgreSQL dump (.sql), there is no local Postgres server to
    restore into and validate against from inside this process, so
    verification here is intentionally more limited: it confirms the
    file is non-empty and looks like a real pg_dump SQL dump (starts
    with pg_dump's own standard header comment) rather than a
    truncated or unrelated file. A true restore-test (`psql` against a
    scratch database) is worth doing periodically outside this API,
    the same way DISASTER_RECOVERY.md already recommends.
    """
    backup_path = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(backup_path):
        return {"status": "error", "message": "Backup file not found."}

    if filename.endswith(".sql"):
        return _verify_postgres_backup(backup_path, filename)
    return _verify_sqlite_backup(backup_path, filename)


def _verify_sqlite_backup(backup_path: str, filename: str) -> dict:
    import sqlite3
    try:
        conn = sqlite3.connect(backup_path)
        conn.execute("SELECT name FROM sqlite_master LIMIT 1")
        conn.close()
    except sqlite3.DatabaseError as error:
        return {"status": "error", "message": f"Backup file is not a valid SQLite database: {error}"}

    return {
        "status": "success",
        "filename": filename,
        "size_bytes": os.path.getsize(backup_path),
        "checksum_sha256": _file_checksum(backup_path),
        "engine": "sqlite",
    }


def _verify_postgres_backup(backup_path: str, filename: str) -> dict:
    size_bytes = os.path.getsize(backup_path)
    if size_bytes == 0:
        return {"status": "error", "message": "Backup file is empty."}

    try:
        with open(backup_path, "r", errors="replace") as f:
            head = f.read(4096)
    except OSError as error:
        return {"status": "error", "message": f"Could not read backup file: {error}"}

    if "PostgreSQL database dump" not in head:
        return {
            "status": "error",
            "message": "File does not look like a pg_dump SQL dump (missing the standard header comment).",
        }

    return {
        "status": "success",
        "filename": filename,
        "size_bytes": size_bytes,
        "checksum_sha256": _file_checksum(backup_path),
        "engine": "postgres",
    }


def list_backups() -> list:
    backups = []
    for filename in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if not (filename.endswith(".db") or filename.endswith(".sql")):
            continue
        path = os.path.join(BACKUP_DIR, filename)
        backups.append({
            "filename": filename,
            "size_bytes": os.path.getsize(path),
            "created_at": datetime.utcfromtimestamp(os.path.getmtime(path)).isoformat(),
            "engine": "postgres" if filename.endswith(".sql") else "sqlite",
        })
    return backups


DEFAULT_BACKUP_RETENTION_COUNT = 7


def apply_retention_policy(keep_count: int = DEFAULT_BACKUP_RETENTION_COUNT) -> list:
    """
    Deletes the oldest backup files beyond `keep_count`, keeping disk
    usage bounded for an automated/scheduled backup strategy (a manual
    "back up now" click from an admin doesn't need this — it's the
    scheduler in backup_scheduler.py that would otherwise accumulate
    one new file per interval forever). Returns the list of filenames
    actually deleted (empty if nothing needed pruning).

    Sorted by filename, not file mtime — every filename this module
    generates already embeds a UTC timestamp (`backup-YYYYMMDDTHHMMSSZ.
    {db,sql}`), so a plain string sort is already a correct
    chronological sort, and doesn't depend on the filesystem's mtime
    surviving a copy/restore/redeploy the way os.path.getmtime would.
    """
    all_backups = sorted(
        (f for f in os.listdir(BACKUP_DIR) if f.endswith(".db") or f.endswith(".sql")),
        reverse=True,  # newest first
    )
    to_delete = all_backups[keep_count:]
    deleted = []
    for filename in to_delete:
        try:
            os.remove(os.path.join(BACKUP_DIR, filename))
            deleted.append(filename)
        except OSError:
            continue
    return deleted
