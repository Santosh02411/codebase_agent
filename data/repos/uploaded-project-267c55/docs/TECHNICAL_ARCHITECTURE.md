# Technical Architecture

## 1. High-Level Flow
```
[Delivery Agent - React App]
        |
        v
  IndexedDB (local storage, works offline)
        |
        v  (when online)
  Sync Engine (client-side)
        |
        v
  FastAPI Backend  <-->  SQLite (source of truth)
        |
        v
[Dispatcher Dashboard - React App]
```

## 2. Components

### 2.1 Frontend (React)
- Two views: Agent view (update deliveries) and Dispatcher view (dashboard)
- All writes from the Agent view go to IndexedDB first, never directly to the
  server
- A sync manager (background check) detects connectivity and triggers sync

### 2.2 Client-Side Storage (IndexedDB)
- Stores delivery records locally with a `sync_status` field: `pending` or `synced`
- Acts as the offline source of truth until synced

### 2.3 Backend (FastAPI)
- Exposes REST endpoints:
  - `POST /deliveries` — create a new delivery record
  - `PATCH /deliveries/{id}` — update status
  - `GET /deliveries` — list all deliveries (for dashboard)
  - `POST /sync` — bulk endpoint agents call with all pending offline changes
- Applies conflict resolution logic on `/sync`

### 2.4 Database (SQLite)
- Single `deliveries` table (schema in `DeliveryRecord`, see below)
- Acts as server-side source of truth once synced

## 3. Data Model

```
DeliveryRecord
- id: string (client-generated UUID)
- agent_id: string
- order_id: string
- status: enum [picked_up, out_for_delivery, delivered, failed_attempt]
- notes: string (optional)
- location_note: string (optional)
- created_at: timestamp
- updated_at: timestamp
- sync_status: enum [pending, synced]   # client-side only field
```

## 4. Conflict Resolution Strategy
**Strategy: Last-write-wins by `updated_at` timestamp.**

When the backend receives a synced record:
1. Check if a record with the same `id` already exists.
2. If not, insert it.
3. If it exists, compare `updated_at` timestamps.
4. Keep whichever record has the later timestamp; discard the other.
5. Return the final resolved record to the client so it can update its local
   copy if the server's version won.

**Known limitation (worth stating in interviews):** last-write-wins can silently
discard a legitimate update if two changes happen close together. A future
iteration could explore field-level merging or vector clocks for more nuanced
resolution — intentionally out of scope for v1 to keep the project shippable.

## 5. Why These Choices
- **IndexedDB over localStorage:** structured, larger-capacity local storage
  suited for multiple records, not just key-value pairs
- **FastAPI over Django:** this project is API-only with no need for
  Django's admin/templating; FastAPI's async support and auto-generated docs
  (Swagger UI) fit better
- **SQLite over MySQL/Postgres initially:** zero setup, keeps focus on sync
  logic rather than database administration; migration path documented for
  later
