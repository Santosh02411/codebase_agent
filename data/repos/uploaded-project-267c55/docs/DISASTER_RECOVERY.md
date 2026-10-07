# Disaster Recovery

This document describes how to recover Delivery Sync's data and
service after data loss, corruption, or an outage. It's written for
the actual deployment modes this project supports (see
`docs/DOCKER.md` and `backend/app/db/session.py`), not a generic
template.

## Scope and honest limitations

Delivery Sync supports two database backends, and both now have real,
working backup — this document is direct about what's automated for
each and what still isn't:

- **SQLite** (the default — `DATABASE_URL` unset): this is a single
  file (`backend/database.db`), backed up via a file-level copy.
- **PostgreSQL** (`DATABASE_URL` set to a `postgres://`/`postgresql://`
  connection string): backed up via a real `pg_dump` subprocess
  against that connection. Requires the `pg_dump` binary to actually
  be installed and on `PATH` wherever the FastAPI process runs (the
  `postgresql-client` package on Debian/Ubuntu, separate from the
  `psycopg2` Python driver this project already depends on) — if it
  isn't, `POST /admin/monitoring/backups` says so plainly rather than
  claiming success.

Both modes are now backed up **automatically on a schedule**
(`BACKUP_INTERVAL_HOURS`, default 24), with old backups pruned down to
a fixed count (`BACKUP_RETENTION_COUNT`, default 7) right after each
successful one — see `backend/app/services/backup_scheduler.py`. An
admin can still trigger a backup manually anytime from the Monitoring
dashboard regardless of this schedule.

**What this still is NOT**, stated plainly: every backup — scheduled
or manual — lives on the **same disk** as the database it's backing
up. There is no offsite/geo-redundant copy, and no point-in-time
recovery between snapshots (only whatever intervals
`BACKUP_INTERVAL_HOURS` gives you). That's a deliberate, honest
boundary — a managed database provider's own automated backups
(RDS snapshots, Supabase backups, etc.) genuinely do more than a
same-host scheduled copy ever can, and layering one of those on top
of (not instead of) what's built here is still the right call for
anything running in real production. This project's backup gets you
"survives disk corruption / accidental bad migration / a bug that
wrote garbage" — not "survives the whole server disappearing."

## Backing up

1. In the admin UI: **Monitoring → Create Backup**, or:
   ```
   curl -X POST https://your-deployment/admin/monitoring/backups \
     -H "Authorization: Bearer <admin access token>"
   ```
   This also happens automatically every `BACKUP_INTERVAL_HOURS` —
   manual triggering is for "I want one right now," not a replacement
   for the schedule.
2. **SQLite**: copies `backend/database.db` to
   `backend/backups/backup-<UTC timestamp>.db` and returns a SHA-256
   checksum of the copy.
   **PostgreSQL**: runs `pg_dump` against `DATABASE_URL` and writes
   `backend/backups/backup-<UTC timestamp>.sql`, likewise with a
   checksum.
3. Right after a **scheduled** (not manual) backup succeeds, old
   backups beyond `BACKUP_RETENTION_COUNT` are deleted automatically —
   oldest first, by the timestamp embedded in the filename.
4. **Copy backups off the server periodically.** A backup that lives
   on the same disk as the original database survives corruption but
   not disk loss — this project's own scheduler doesn't do that
   copy-off-host step for you; script a periodic job (cron, a
   scheduled CI job, etc.) that pulls new files from
   `backend/backups/` to separate storage (S3, a different host,
   etc.), or point `BACKUP_RETENTION_COUNT`/your own tooling at
   whatever offsite policy you actually need.

### Verifying a backup

`GET /admin/monitoring/backups/{filename}/verify` (or the "Verify"
button in the admin UI) does real validation, not just a checksum
match:

- **SQLite `.db` backups**: recomputes the SHA-256 checksum AND
  actually opens the file as a SQLite database and runs a trivial
  query against it. A file that copied successfully but is truncated
  or corrupted mid-write is exactly the failure mode a checksum alone
  won't catch — only actually opening it as a database will.
- **PostgreSQL `.sql` backups**: recomputes the checksum and confirms
  the file is non-empty and starts with `pg_dump`'s own standard
  header comment, catching a truncated or unrelated file. A true
  restore-test (`psql` against a scratch database) needs a real
  Postgres server to restore into, which this process doesn't have —
  worth doing periodically as a manual or CI step, same spirit as the
  next line.

Run verification periodically on your most recent backups, not just
once at creation time — disk-level bit rot can happen after the fact.

## Restoring (SQLite)

1. Stop the application (`docker compose down`, or however it's
   running).
2. Move the current (possibly corrupted/lost) `backend/database.db`
   aside, in case it's still partially useful for forensics:
   ```
   mv backend/database.db backend/database.db.broken
   ```
3. Copy the chosen backup file into place:
   ```
   cp backend/backups/backup-<timestamp>.db backend/database.db
   ```
4. Restart the application. `Base.metadata.create_all()` (see
   `main.py`) will add any newly-introduced tables from schema changes
   released since that backup was taken — it does not drop or alter
   existing tables, so the restored data is preserved.
5. Check `GET /health/db` responds `{"status": "ok"}` and spot-check a
   few known records via the admin UI.

## Restoring (PostgreSQL)

1. Stop the application.
2. Restore the `.sql` dump into a fresh/target database with `psql`:
   ```
   psql "$DATABASE_URL" -f backend/backups/backup-<timestamp>.sql
   ```
   (Use a scratch database first if you want to verify the dump before
   overwriting anything live — this project's own `pg_dump` invocation
   uses `--no-owner --no-privileges`, so the dump is portable across
   role/ownership setups.) Or use your provider's own point-in-time
   recovery if that's available and preferred.
3. Restart the application, pointed at the restored database.
   `Base.metadata.create_all()` behaves the same way described above.
4. Check `GET /health/db` responds `{"status": "ok"}` and spot-check a
   few known records via the admin UI.

## Migration safety

Schema changes across the phases of this project have all been
**additive**: new tables, and new nullable/defaulted columns on
existing tables (see `docs/FEATURE_LOG.md` — every phase's entry
documents this explicitly). `Base.metadata.create_all()` only ever
creates tables that don't exist yet; it never drops or alters an
existing one. This means:

- Upgrading to a newer version of this codebase against an existing
  database is safe to do without a backup-first step, in the sense
  that no existing data or column is ever dropped by the startup
  migration path.
- New nullable columns on an existing table (e.g. Phase 15's
  `ProductDB.cost_price`, Phase 16's organization branding fields)
  simply don't exist as a concept for rows written before that
  release — they read back as `NULL`/`None`, which every consumer of
  those fields is written to handle (see each phase's `FEATURE_LOG.md`
  entry for the specific "what happens to old rows" note).
- **Still take a backup before any schema/dependency upgrade anyway.**
  "The migration path is additive-safe" is a statement about this
  application's own code; it says nothing about human error, a bad
  `git checkout`, or a dependency upgrade that behaves unexpectedly.

There is no separate down-migration/rollback tooling in this project
— rolling back a bad deploy means restoring the pre-deploy backup, not
running a reverse migration.

## Alerting

Two channels currently exist for surfacing problems, both real and
already wired in — not a placeholder:

- **Security alerts** (Phase 17): `services/email.py`'s
  `send_security_alert_email()` fires on a suspicious login, a
  password change, 2FA being disabled, or an all-devices logout — sent
  to the affected user directly.
- **Monitoring dashboard** (Phase 18): `GET /admin/monitoring/status`
  surfaces database health, every background job's heartbeat/health,
  and live WebSocket connection counts in one call — the admin UI's
  Monitoring page polls this on load. There is no push-based alerting
  (e.g. paging an on-call engineer) implemented — that would need a
  real external alerting integration (PagerDuty, Slack webhook, etc.)
  with credentials this environment doesn't have, the same "bring your
  own credentials, or it no-ops" pattern already established for
  Razorpay/SMTP/push/Google geocoding elsewhere in this project. An
  admin checking the Monitoring page (or scripting a periodic call to
  `/admin/monitoring/status` and `/health/db`) is the current source
  of truth for "is anything wrong."
