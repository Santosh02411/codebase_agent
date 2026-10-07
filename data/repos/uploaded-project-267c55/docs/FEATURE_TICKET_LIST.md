# Feature Ticket List

Tracked as simple tickets — mirrors how real teams break work into units.
Update status as you go: `TODO` / `IN PROGRESS` / `DONE`.

## Phase 1 — Backend Skeleton
- [x] TICKET-1: Define `DeliveryRecord` model (Pydantic + SQLite schema)
- [x] TICKET-2: Set up FastAPI project structure + SQLite connection
- [x] TICKET-3: Build `POST /deliveries` (create)
- [x] TICKET-4: Build `PATCH /deliveries/{id}` (update status)
- [x] TICKET-5: Build `GET /deliveries` (list for dashboard)

## Phase 2 — Offline Frontend
- [x] TICKET-6: Scaffold React app structure
- [x] TICKET-7: Set up IndexedDB wrapper (create/read/update local records)
- [x] TICKET-8: Build Agent View UI (list + status updater)
- [x] TICKET-9: Add connectivity detection (online/offline banner)

## Phase 3 — Sync Engine
- [x] TICKET-10: Build `POST /sync` endpoint with conflict resolution logic
- [x] TICKET-11: Build client-side sync trigger (runs on load, on reconnect,
  and periodically every 15s while online)
- [x] TICKET-12: Handle partial sync failures + retry logic
- [x] TICKET-13: Update local IndexedDB records after successful sync
  (mark as "synced")

## Phase 4 — Dashboard & Agent View Polish
- [x] TICKET-14: Build Dispatcher dashboard table view
- [x] TICKET-15: Add filtering by delivery status
- [x] TICKET-16: Add manual refresh action
- [x] TICKET-16a (added mid-phase): Sort Agent view deliveries by most
  recently updated first
- [x] TICKET-16b (added mid-phase): Add delete functionality for delivery
  records (local + server, with confirmation prompt)

## Phase 5 — Polish & Resume-Readiness
- [ ] TICKET-17: Write full README with architecture diagram
- [ ] TICKET-18: Record a short demo GIF (offline update → reconnect → sync)
- [ ] TICKET-19: Push clean commit history to GitHub
- [ ] TICKET-20 (optional): Deploy backend + frontend to Render
