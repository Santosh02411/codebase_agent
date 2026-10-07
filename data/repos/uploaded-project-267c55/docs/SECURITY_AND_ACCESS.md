# Security & Access

## 1. User Roles
| Role | Access |
|------|--------|
| Delivery Agent | Can create/update delivery records assigned to them |
| Dispatcher | Can view all delivery records and their statuses |

## 2. Authentication (v1 scope)
- Simple token-based authentication (JWT) issued on login
- Each agent's requests are tagged with their `agent_id` from their token —
  agents cannot spoof another agent's ID
- Dispatcher accounts have a separate role flag to access the dashboard/list-all
  endpoint

## 3. Data Validation
- All incoming sync payloads validated against the `DeliveryRecord` schema
  (FastAPI + Pydantic handles this automatically)
- Reject malformed timestamps or unknown status values before they reach the
  database

## 4. Data Integrity During Sync
- Each record's `id` is a client-generated UUID to avoid collisions across
  devices
- Server never trusts client `sync_status` — it's a client-side-only field and
  recalculated after each successful sync

## 5. What's Explicitly Out of Scope (v1)
- Encryption at rest (SQLite file is not encrypted in v1 — acceptable for a
  demo project, would be required before any real production use)
- Rate limiting / abuse protection
- Multi-tenant data isolation (only one "organization" assumed for now)

## 6. Notes for Future Hardening
If this were to move toward production use, next steps would include:
HTTPS enforcement, hashed/salted credential storage, rate limiting on the
`/sync` endpoint, and audit logging of who changed what and when.
