# Project Workflow — Detailed Build Log

This document is a detailed, phase-by-phase account of how this project was
built: what was built in each phase, and — importantly — every real error,
bug, or mistake encountered along the way, which file it was in, why it
happened, and exactly how it was fixed. This is intentionally detailed and
written so it can be read on its own to understand the project deeply enough
to explain it confidently in an interview, not just to skim.

---

## Phase 1 — Backend Skeleton

**Goal:** Set up the FastAPI backend with a `DeliveryRecord` model and basic
CRUD (create, read, update, list) endpoints, backed by SQLite.

**What was built:**
- `backend/app/db/session.py` — SQLAlchemy engine + session setup for SQLite
- `backend/app/models/delivery.py` — the `DeliveryRecord` model, defined
  twice on purpose: once as `DeliveryRecordDB` (the actual database table,
  using SQLAlchemy) and once as several Pydantic schemas
  (`DeliveryRecordCreate`, `DeliveryRecordUpdate`, `DeliveryRecordOut`) that
  define what shape of data the API accepts and returns. Keeping these
  separate is a deliberate design choice: the database structure can evolve
  independently of what the API exposes to clients.
- `backend/app/routes/deliveries.py` — the actual endpoints:
  `POST /deliveries/` (create), `PATCH /deliveries/{id}` (update),
  `GET /deliveries/` (list all), `GET /deliveries/{id}` (get one)
- `backend/main.py` — the FastAPI app entry point, which creates the database
  tables on startup and wires the routes into the app

**Errors / issues faced in this phase:** None — this phase was tested
immediately using FastAPI's `TestClient` (create → list → update, all
verified working) before being handed over, so no bugs surfaced here later.

---

## Phase 2 — Offline-Capable Frontend

**Goal:** Build the React frontend, with an Agent view that saves data to
IndexedDB first (so it works fully offline), and a Dispatcher view that
reads directly from the backend.

**What was built:**
- `frontend/src/services/indexedDb.js` — a hand-written wrapper around the
  browser's raw IndexedDB API (no external library), with functions to save
  a record locally, get all local records, get only unsynced ("pending")
  records, and mark a record as synced.
- `frontend/src/services/api.js` — functions that call the FastAPI backend
  over HTTP (create, update, list, and later, sync).
- `frontend/src/hooks/useConnectivity.js` — a small React hook that tracks
  whether the browser is online or offline, using the browser's built-in
  `online`/`offline` events.
- Components: `ConnectivityBanner`, `SyncStatusBadge`, `DeliveryStatusUpdater`,
  `AgentDeliveryList` (the main agent-facing view), `DispatcherTable`.
- `App.jsx` — ties the Agent and Dispatcher views together with a simple
  toggle.
- Build tool: **Vite** was chosen over Create React App, since CRA is
  deprecated and Vite is the current standard, faster to start, and doesn't
  change how React itself is written.

### Error #1 — JSX files with the wrong extension

**What happened:** The very first time the frontend was run with
`npm run dev`, Vite failed with:
```
The JSX syntax extension is not currently enabled
src/App.js:10:4: <div>
```

**Why it happened:** `App.js` and `index.js` were originally created with a
plain `.js` extension, but they contained JSX syntax (things like `<div>`,
`<App />`). Vite's underlying bundler (esbuild) only automatically enables
JSX parsing for files ending in `.jsx` (or `.tsx`) — a `.js` file is assumed
to be plain JavaScript with no JSX inside it, so esbuild refuses to parse
the JSX and throws this error instead of guessing.

**File affected:** `frontend/src/App.js`, `frontend/src/index.js`

**How it was fixed:** Both files were renamed to `App.jsx` and `index.jsx`.
The one place that referenced the old filename — the `<script>` tag in
`frontend/index.html` pointing to `/src/index.js` — was updated to point to
`/src/index.jsx` instead.

**A follow-up mistake:** After sharing the renamed files, the same error
still appeared. This was because the *old* `App.js`/`index.js` files were
never actually deleted from the project folder before the new `.jsx` files
were added — both versions existed side by side. Vite's default module
resolution checks for a `.js` file before a `.jsx` file with the same name,
so it kept loading the old, broken `App.js`. The real fix required deleting
the entire old `frontend` folder and replacing it cleanly, not just adding
new files on top of old ones — a good general lesson: when replacing files
with a different extension, the old file must be explicitly removed, not
left alongside the new one.

---

## Phase 3 — Sync Engine with Conflict Resolution

**Goal:** Build the piece that actually pushes offline-saved records to the
backend once connectivity returns, and resolves conflicts if the same record
was changed in two places.

**What was built:**
- `backend/app/services/conflict_resolver.py` — the core conflict resolution
  logic: last-write-wins based on the `updated_at` timestamp. If an incoming
  record's timestamp is newer than what the server already has, the incoming
  change wins; otherwise, the server's existing version is kept.
- `backend/app/routes/sync.py` — the `POST /sync` endpoint, which accepts a
  batch of records from the client and applies the conflict resolution logic
  to each one, returning the final resolved version of each record.
- `frontend/src/services/syncEngine.js` — the client-side piece: `runSync()`
  gathers all pending (unsynced) local records and sends them to `/sync`,
  with retry logic (up to 3 attempts) if the request fails; `startAutoSync()`
  wires this up to run automatically.

This phase surfaced two real bugs — both are genuinely useful to describe in
an interview, since they're common, realistic problems in real sync systems,
not contrived ones.

### Error #2 — CORS misconfiguration (wildcard origin + credentials)

**What happened:** After building the sync engine, clicking "Sync Now" in
the browser failed with a vague `Sync failed: Failed to fetch` error, even
though the backend was confirmed to be running (its Swagger UI at
`/docs` loaded fine).

**Why it happened:** In `backend/main.py`, the CORS middleware (which
controls which frontend origins are allowed to call the API) was configured
with both `allow_origins=["*"]` (allow requests from any origin) **and**
`allow_credentials=True` (allow cookies/credentials) at the same time.
Browsers explicitly reject this exact combination for security reasons —
per the Fetch spec, a server cannot say "anyone can call me" and "also send
me your credentials" simultaneously, since that would be a security hole.
When a browser detects this combination in a response, it blocks the entire
response silently, which shows up in JavaScript as a generic, unhelpful
"Failed to fetch" error rather than a clear CORS message — making this
particularly tricky to diagnose without knowing this specific browser rule.

**File affected:** `backend/main.py`

**How it was fixed:** Since this project doesn't use cookies or
credential-based auth at all, `allow_credentials` was changed from `True` to
`False`. This makes the `allow_origins=["*"]` (allow-all) setting valid
again, since the invalid combination no longer exists. Verified afterward by
simulating a browser's CORS "preflight" request directly against the backend
and confirming the response headers were now consistent
(`Access-Control-Allow-Origin: *` with no conflicting credentials header).

### Error #3 — Comparing timezone-aware and timezone-naive datetimes

**What happened:** After the CORS fix, syncing worked for some records but
failed for others (and eventually for all new records), with the backend
terminal showing:
```
TypeError: can't compare offset-naive and offset-aware datetimes
```
at the exact line in `conflict_resolver.py` that compares timestamps to
decide which version of a record should win.

**Why it happened:** JavaScript's `new Date().toISOString()` (used on the
frontend to timestamp every change) produces a string like
`2026-07-22T19:10:46.276Z`. The trailing `Z` means "this timestamp is in
UTC" — Python's datetime parser reads this as a **timezone-aware** datetime
(it carries an explicit timezone marker). However, when FastAPI/SQLAlchemy
reads a timestamp back out of SQLite, it comes back as a **timezone-naive**
datetime (no timezone marker attached at all, since the `DateTime` column in
the model wasn't configured to store timezone info). Python's `>` comparison
operator refuses to compare an aware datetime with a naive one, since it's
ambiguous which timezone the naive one is actually in — so it raises a
`TypeError` instead of guessing.

**File affected:** `backend/app/services/conflict_resolver.py`

**How it was fixed:** A small helper function, `_normalize_to_naive_utc()`,
was added at the top of the file. Before any comparison or database write
happens, every incoming timestamp is passed through this function: if it has
timezone info attached, it's first converted to UTC (in case it was in some
other timezone) and then has the timezone marker stripped off, leaving a
plain naive datetime that's guaranteed to represent UTC. Both `created_at`
and `updated_at` on every incoming record are normalized this way as the very
first step inside `resolve_and_apply()`, before anything else happens to
them. This guarantees that every datetime being compared or stored from this
point onward is consistently naive UTC, so the `>` comparison always works
safely. This was verified by re-running the exact same sync request that had
previously failed, using the exact `Z`-suffixed timestamp format the browser
actually sends, and confirming both a fresh sync and a conflicting
(older-timestamp) sync both resolved correctly with no error.

### Error #4 (minor) — Auto-sync only triggered on component remount

**What happened:** This wasn't a crash or error message, but an observed gap
in behavior: while online, newly added or updated deliveries stayed marked
"Saved locally" and did not sync automatically — they only became "Synced"
if the "Sync Now" button was clicked, or if the Dispatcher/Agent view was
switched and switched back, or if the page was refreshed.

**Why it happened:** The auto-sync setup (`startAutoSync`) was only wired to
run in two situations: once when the `AgentDeliveryList` component first
mounted, and again whenever the browser's `online` event fired (i.e. going
from offline to online). Switching views or refreshing the page happened to
also re-trigger a sync, but only as a side effect of the component
re-mounting from scratch — not because of any deliberate "sync periodically"
logic. If the user stayed on the Agent view continuously while already
online, nothing would prompt another sync attempt until one of those
specific events happened again.

**File affected:** `frontend/src/services/syncEngine.js`

**How it was fixed:** A third auto-sync trigger was added: a
`setInterval()` that calls the sync check every 15 seconds while the browser
is online, independent of component mounting or connectivity-change events.
The cleanup function returned by `startAutoSync()` was also updated to clear
this interval (in addition to removing the `online` event listener), to
avoid leaving a timer running in the background if the component using it
is ever removed from the page.

---

## Phase 4 — Dispatcher Dashboard Polish & Agent View Improvements

**Goal:** Add status filtering to the Dispatcher dashboard, and address two
usability gaps noticed in the Agent view during testing: deliveries appeared
in arbitrary order, and there was no way to remove a delivery record.

**What was built:**
- `backend/app/routes/deliveries.py` — added a `DELETE /deliveries/{id}`
  endpoint. Deliberately designed to not error if the record doesn't exist
  on the server (returns `{"deleted": false, "reason": "not found on
  server"}` instead) — this matters because a record might only ever have
  existed locally and never been synced, which is a normal, expected case,
  not an error condition.
- `frontend/src/services/indexedDb.js` — added `deleteDeliveryLocally(id)`
  to remove a record from local IndexedDB storage.
- `frontend/src/services/api.js` — added `deleteDeliveryOnServer(id)` to
  call the new backend endpoint.
- `frontend/src/components/AgentDeliveryList.jsx` — two changes:
  1. `loadFromLocalStorage()` now sorts records by `updated_at` descending
     (most recently changed first), instead of relying on IndexedDB's
     arbitrary/insertion order.
  2. Added a `handleDelete()` function and a Delete button per card, with a
     confirmation prompt. Deletes locally first always; if the record was
     already synced, also attempts to delete it from the server (a
     best-effort call — if this fails, e.g. because the agent is offline,
     the error is only logged to the console, since the local delete
     already succeeded and is what matters for the agent's immediate view).
- `frontend/src/components/DispatcherTable.jsx` — added a status filter
  dropdown (All / Picked Up / Out for Delivery / Delivered / Failed
  Attempt) with a "Showing X of Y" count, and sorted the table by most
  recently updated first, matching the Agent view's sort order.

**Errors / issues faced in this phase:** None — each piece was verified
before being shared: the DELETE endpoint was tested with `TestClient`,
including the edge case of deleting a record that was already deleted (to
confirm it returns a clean "not found" response instead of crashing), and
all modified JS/JSX files were syntax-checked before delivery.

**A process note worth recording:** these two additions (ordering and
delete) were not part of the original Phase 4 scope in the ticket list —
they came up organically while testing Phase 3's sync behavior. This is a
completely normal and expected part of real software development: using a
feature surfaces small gaps that weren't obvious during planning. Deciding
where to slot them in (here: added into Phase 4 rather than deferred) is
itself a small scoping decision worth being able to explain.

## Phase 5 — Authentication, Roles & Delivery Assignment

**Goal:** Replace the placeholder single-agent setup (a hardcoded
`agent-001`) with real accounts, login/logout, and role-based access —
agents and dispatchers as genuinely different users with different
permissions, plus a real assignment flow (dispatcher assigns work to a
specific agent) instead of agents self-creating "sample" deliveries.

**What was built:**
- `backend/app/models/user.py` — `UserDB` table (username, hashed
  password, role, display name) plus signup/login/output schemas
- `backend/app/services/auth.py` — password hashing (bcrypt via passlib)
  and JWT creation/verification
- `backend/app/routes/auth.py` — `/auth/signup`, `/auth/login`, and a
  `get_current_user` dependency other routes use to identify who's calling
- `backend/app/routes/deliveries.py` — updated so `POST /deliveries/`
  (create/assign) is dispatcher-only, `GET /deliveries/` (full list) is
  dispatcher-only, and a new `GET /deliveries/mine` returns only the
  logged-in agent's assigned deliveries
- `backend/app/routes/users.py` — `GET /users/agents`, letting a
  dispatcher list all registered agents for the assignment dropdown
- Frontend: `AuthContext.jsx` (session state, persisted to localStorage),
  `LoginPage.jsx` / `SignupPage.jsx`, and a "pull-sync" addition to the
  Agent view — agents now periodically fetch their assigned deliveries
  from the server (`fetchMyDeliveriesFromServer`) and merge them into
  IndexedDB, rather than only ever seeing locally self-created records

**Errors faced in this phase:**

1. **`passlib`/`bcrypt` version incompatibility.** Newer `bcrypt` releases
   removed an internal attribute (`__about__.__version__`) that `passlib`
   expects, causing password hashing to fail immediately on signup. Fixed
   by pinning `bcrypt==4.0.1` in `requirements.txt` — a real, common
   dependency-compatibility issue, not a mistake in the app's own code.

2. **File-sharing naming collisions.** Several new files were both named
   `auth.py` (one under `models/`, one under `services/`, one under
   `routes/`) — Claude's file-sharing tool can't present multiple files
   with the same display name at once, so they were shared under
   temporary names (`auth_service.py`, `auth_routes.py`). This caused real
   confusion: pasting a file under its *shared* name instead of renaming
   it back to what the code actually imports (`auth.py` in each folder)
   produced `ImportError` / `ModuleNotFoundError` on backend startup.
   **Lesson:** when a shared filename differs from its destination
   filename, that rename step is not optional — Python resolves imports by
   the literal file name on disk, not by any label attached when it was
   shared.

3. **CORS misconfiguration (`allow_origins=["*"]` + `allow_credentials=True`).**
   Once the frontend started sending real requests to protected endpoints,
   syncing failed with a generic "Failed to fetch." Root cause: browsers
   reject a CORS response that allows any origin AND allows credentials at
   the same time (a deliberate security restriction). Fixed by setting
   `allow_credentials=False`, since this project doesn't use cookies.

---

## Phase 6 — Status History, Toast Notifications & Summary Stats

**Goal:** Add an audit trail (who changed what, when), replace plain
inline status messages with proper toast notifications, and give the
dispatcher a live summary of delivery counts by status.

**What was built:**
- `backend/app/models/delivery_history.py` + `services/history.py` — a
  `delivery_history` table logging every create/update (old status → new
  status, who did it, when), written to automatically from both the
  normal `PATCH /deliveries/{id}` route and the offline `/sync` path
- `GET /deliveries/{id}/history` — returns the full timeline for one delivery
- Frontend: `DeliveryDetailModal.jsx` fetches and displays this timeline;
  `ToastContext.jsx` provides app-wide toast notifications, replacing
  inline "Synced!" / "Assigned!" text; `DispatcherTable.jsx` gained stat
  cards (counts per status, delivered-today) computed from the same data
  already being fetched — no extra API calls needed

**Errors faced in this phase:** None new — this phase built cleanly on
the now-stable auth/assignment foundation from Phase 5, and each piece
(history logging, the `/history` endpoint) was verified with
`TestClient` before being wired into the frontend.

---

## Phase 7 — Full Visual Redesign & Light/Dark Theme

**Goal:** Replace the plain, inline-styled interface with a genuine
visual identity — sidebar navigation, a proper typography system, and a
dark "fleet ops console" aesthetic fitting a logistics product, plus a
light/dark toggle with guaranteed readability in both modes.

**What was built:**
- `frontend/src/styles/theme.css` — one shared set of CSS variables
  (colors, fonts, spacing) used by every component; a
  `html[data-theme="light"]` override block redefines those same variable
  names with re-tuned (not just inverted) values for light mode
- `ThemeContext.jsx` — toggles the `data-theme` attribute and persists the
  choice to localStorage
- `Sidebar.jsx` — real navigation (My Deliveries / Performance for agents,
  Dashboard for dispatchers), replacing the old top-bar view switcher
- Every existing component (`AgentDeliveryList`, `DispatcherTable`,
  `DeliveryDetailModal`, badges, buttons, auth pages) was rewritten to use
  the shared theme classes instead of one-off inline styles
- New: `AgentPerformance.jsx` (completed today/this week, completion
  rate) and `Pagination.jsx` (used by both the Agent and Dispatcher lists)

**Errors faced in this phase:**

1. **Two small class/style mismatches caught before delivery.** A
   `.mono` utility class was used in JSX but never defined in
   `theme.css`, and one button used a class name
   (`btn-outline-accent`) that didn't match what the stylesheet actually
   defined (`btn-info-outline`). Both were caught by writing a small
   cross-check (comparing every `className` used in the JSX against every
   class actually defined in the CSS) rather than by visual inspection —
   worth knowing as a general technique: for a redesign this size, a
   scripted consistency check catches mismatches that are easy to miss by
   eye, especially for classes that don't render as visibly "broken" (an
   unstyled button still looks like *a* button, just not the right one).

---

## Phase 8 — Operational Depth (Route Batching, Time Estimates, Bulk Import)

**Goal:** Add features expected of a genuine logistics tool beyond basic
status tracking: grouping/ordering an agent's deliveries by area, a
deadline concept with overdue flagging, and bulk-assigning many
deliveries at once from a CSV instead of one at a time.

**What was built:**
- `backend/app/models/delivery.py` — added `zone`, `latitude`,
  `longitude` (all optional strings) and `expected_by` (optional
  datetime) to the delivery record
- `backend/app/routes/bulk_import.py` — `POST /deliveries/bulk-import`,
  processing each CSV row independently so one bad row (unknown agent,
  blank order ID) doesn't block the valid rows in the same file
- `frontend/src/services/csvParser.js` — a hand-written CSV parser
  (quoted fields, embedded commas, escaped quotes, CRLF line endings all
  handled) rather than a naive `text.split(',')`, which breaks the moment
  a notes field contains a comma
- `frontend/src/services/routeOptimizer.js` — groups an agent's active
  deliveries by zone, and — where coordinates are available — orders them
  within each zone via a nearest-neighbor heuristic (a deliberate,
  explainable approximation, since true optimal routing is NP-hard),
  anchored to the agent's live position via browser geolocation where
  permitted
- `SuggestedRoute.jsx`, `BulkImportPanel.jsx` — the corresponding UI

**Errors faced in this phase:**

1. **Stale SQLite schema after adding new columns.** After adding `zone`,
   `latitude`, `longitude`, and `expected_by` to the `DeliveryRecordDB`
   model, syncing and fetching deliveries started failing with
   `sqlalchemy.exc.OperationalError: no such column: deliveries.zone`.
   Root cause: `Base.metadata.create_all()` (called on every backend
   startup) only creates tables that don't exist yet — it does **not**
   alter an already-existing table to add newly-defined columns. Since
   `database.db` had been created earlier in the project (back when the
   table only had the original columns), it kept its old structure no
   matter how many times the backend restarted, until the file itself was
   deleted so a fresh one could be created with the current, correct
   schema. **This is a genuine, common real-world issue** — production
   systems handle this with a proper migration tool (e.g. Alembic) that
   applies incremental schema changes to an existing database without
   losing its data; deleting and recreating the file is only an
   acceptable fix here because this is local development/demo data with
   nothing worth preserving. Worth stating plainly in an interview if
   asked "how would you handle a schema change in production?" — the
   honest answer is "not the way this project did it locally."

---

## Phase 9 — Final Polish & Resume Readiness (not started)

*(This section will be filled in once Phase 9 work happens.)*

---

## Phase 10 — Recurring Orders & Marketplace Polish

**Recurring/subscription orders**, built on top of a design decision
made explicitly up front (avoids the two easy wrong turns a "make it
recurring" feature invites): payment is never auto-charged — every
cycle is a real `pending_payment` Order the customer must confirm and
pay themselves, same as an abandoned-cart order today. This meant the
actual engineering work was almost entirely reuse rather than new
payment logic: `routes/subscriptions.py`'s `initiate-payment` endpoint
is a near-line-for-line copy of `checkout()`'s Razorpay/COD/test-mode
tail, applied to an order the scheduler already built instead of one
built fresh from a cart — and `POST /customer/checkout/verify` needed
zero changes at all, since it was already written generically against
"any pending_payment order owned by this customer," not "an order this
endpoint just created." The one real new piece is
`services/subscription_scheduler.py`'s `run_subscription_cycle` — an
`asyncio` background task (not APScheduler/Celery — this project stays
zero-extra-infra, and a 60-second `asyncio.sleep` loop started from
FastAPI's `on_event("startup")` is genuinely sufficient at this scale)
that finds every due subscription, builds its order at *today's* stock
and prices (never the prices from when the subscription was created —
a subscription is "reorder this," not "re-charge this exact receipt"),
and always advances `next_run_date` by the interval regardless of
whether that cycle's order ever gets paid, so an ignored reminder can't
silently freeze every future cycle too.

**Multi-vendor marketplace**: investigating this ticket turned up that
the hard part — real multi-tenancy — already existed. `OrganizationDB`
was already "one org = one independently-run store"; `CustomerDB` was
already a global identity deliberately separate from the org-scoped
staff `UserDB` specifically because a customer "may have deliveries
from many different companies" (see that model's own docstring);
`CartItemDB` was already scoped to one store at a time "same behavior
as Swiggy/Zomato/Amazon-marketplace carts"; and `GET /stores` already
listed every opted-in store to browse. What was missing was purely
findability: a store had nothing beyond a bare name to distinguish it
in a directory of many, and no way to search or filter that directory
at all. Fixed with two new optional `OrganizationDB` columns
(`category`, `description`) and query params on the existing `GET
/stores` endpoint — no new tables, no change to the cart/checkout
architecture, because none was needed.

Both features passed full TestClient verification (subscription
create → run-now → initiate-payment → verify → paid-with-real-delivery;
insufficient-stock line-skipping; cross-customer subscription-ownership
isolation; invalid-interval rejection; marketplace search/category
filtering, case-insensitive) and a full-project `esbuild` bundle check
came back clean.

---

## Adding Admin Action Logging Without Breaking Offline Caching

Two features requested together: a general admin action log ("who
changed what, when" beyond just delivery status), and pagination on
the large list endpoints. The action log was straightforward — a new
table, a small diffing helper, and a handful of `record_action(...)`
calls dropped into existing write endpoints. The pagination part had
a real trap in it.

The naive version — add `limit`/`offset` with sane defaults to every
unpaginated list endpoint — would have been wrong for two of them.
`GET /deliveries/` and `GET /deliveries/mine` (the dispatcher/agent
lists) don't just render a table; their response is also what gets
written into IndexedDB via `cacheDispatcherDeliveries()` /
`cacheCustomerDeliveries()`-equivalent calls, which is the entire
mechanism that makes the dashboards usable when a delivery agent loses
signal in the field — the whole premise of this being an "offline-
first" app. Slapping a default `limit=100` on that endpoint (which I
did briefly, then caught before shipping it) would have silently
truncated the offline cache for any org with more than 100 delivery
records — the kind of bug that wouldn't show up in a demo with a
handful of seeded deliveries, only months later when it actually
matters, and offline mode would just quietly stop working for older
records with no error anywhere.

The fix: leave those two endpoints as full, unpaginated fetches (with
a comment explaining why), since the dispatcher table already paginates
on-screen client-side over the fully-cached data — the right layer to
page something that's already local. Applied real server-side
pagination only where there's no offline-cache dependency:
`/customer/orders` and `/customer/notifications` (default `limit=20`),
plus `/customer/deliveries` with limit/offset made *optional* rather
than defaulted, since that one endpoint does double duty — it's both
the main "load my orders" call AND the seed for the customer's own
offline delivery cache.

That optional-pagination fix surfaced one more real bug in a code
review pass: `CustomerDeliveryCard`'s cancelled-order handling called
`fetchMyOrders(token)` with no filter, then searched the returned array
client-side for the one order matching the current delivery, purely to
read its refund status. Once `/customer/orders` got a `limit=20`
default, that lookup would silently return nothing for any cancelled
order more than 20 purchases back — refund status would just stop
showing up for older cancellations, no error, easy to miss entirely in
testing since it only breaks past the 20th order. Fixed by adding a
`delivery_id` query filter to `GET /customer/orders` and switching that
one call site to use it, instead of scanning an increasingly-partial
list.

Lesson worth remembering: "add pagination to the unpaginated endpoints"
sounds like a mechanical, uniform change, but a couple of these
endpoints were quietly load-bearing for something other than what a
list endpoint normally does (seeding an offline cache; being scanned
client-side as an ad-hoc lookup). Grepping for every call site of an
endpoint before changing its default behavior — not just skimming the
route handler itself — is what caught both issues here before they
shipped.

---

## Reusing an Existing Component Instead of Building a Second One

When adding a live agent-location map to the public tracking page, the
tempting shortcut was to write a new, simpler map component scoped to
"public tracking only." But `LiveTrackingMap.jsx` already existed — it
was built earlier for the logged-in customer dashboard, complete with
offline tile caching, a WebSocket live-update subscription, and a
30-second polling safety net. Writing a second component would have
meant maintaining two copies of all of that, one of which would
inevitably drift out of sync with the other over time (a classic
source of "why does the map behave differently on these two pages"
bugs).

Instead, the existing component was extended to accept an optional
`token` prop: pass one and it calls the logged-in customer endpoint,
omit it and it calls a new public endpoint instead — same rendering
logic, same caching, same WebSocket handling either way, since the
tracking WebSocket was already unauthenticated (scoped to an
unguessable delivery UUID, the same security model as the public
tracking page itself). The only genuinely new code was the new public
backend endpoint and a two-line branch inside the existing `poll()`
function.

The backend side of that new endpoint got one deliberate restriction
the logged-in version doesn't have: it only returns a position while
the delivery is `picked_up` or `out_for_delivery`. The logged-in
customer endpoint doesn't bother with that check, because ownership
(the delivery has to belong to the requesting customer) already limits
who can ask. The public endpoint has no login at all — anyone with the
tracking link can call it — so it needed its own limit on *when* a
position is exposed, not just relying on the fact that the agent's
identity is never included in the response. Scoping it to exactly the
two statuses the existing location-broadcast WebSocket code
(`routes/users.py`) already uses for its live pushes was a deliberate
choice too: it means the one-off REST fetch and the real-time updates
can never disagree about whether a position counts as "currently
live," which would otherwise be an easy way to introduce a subtle bug
(map shows a stale pin because the REST call succeeded under a looser
rule than the WebSocket was using).

---

## A Route-Ordering Bug Caught Before It Shipped

Adding `PATCH /deliveries/bulk-status` and `PATCH /deliveries/bulk-assign-agent`
looked like a pure addition — new endpoints, nothing existing should
change. The first draft appended both route functions near the bottom
of `deliveries.py`, after the existing single-record
`PATCH /{delivery_id}`. That's the kind of ordering mistake that's easy
to miss in review, because the code reads fine top to bottom and every
individual endpoint is correct in isolation.

FastAPI (like most routers) matches routes in declaration order, and
`/{delivery_id}` is a wildcard that matches *any* path segment —
including literally the string "bulk-status". With the bulk routes
declared after it, a request to `PATCH /deliveries/bulk-status` would
never reach the bulk handler at all: it'd match `/{delivery_id}` first,
try to look up a delivery with the literal id `"bulk-status"`, and
return a 404. The bulk endpoints would have been completely
unreachable, and nothing in a quick manual check (hitting them
directly, expecting a 404 on a fresh/empty selection anyway) would
have made that obvious — the failure mode looks identical to "no
matching deliveries," not "route doesn't exist."

Caught it by remembering the file already had this exact class of
ordering requirement — `/unassigned` and `/mine` are deliberately
declared before their own `/{delivery_id}` catch-alls, which is
mentioned nowhere in a comment, just baked into the file's existing
route order. Grepping the file's full endpoint list before adding
anything new — not just eyeballing where the new code visually fit —
surfaced the mismatch immediately, and the fix was a pure reordering,
no logic changes needed. Same lesson as the offline-cache pagination
issue from the previous session: a change that looks additive can
still interact with an existing, unstated invariant elsewhere in the
file, and the way to catch that is to check the file's actual current
behavior before assuming "I only added new code" means "nothing else
could have changed."

---

## A Test-Isolation Bug That Was Already There, Waiting

Three new backend test files landed alongside the security-hardening
work. All three passed individually. Run as part of the FULL suite,
four tests failed — two of them in a file (`test_staff_account_settings.py`)
that hadn't been touched this session at all, with an error that made
no sense on its face: "Another account already uses that email," for
an email literal that appeared nowhere else in the entire test suite.

Bisecting which combination of test files triggered it narrowed the
cause to one specific file always being present: `test_rate_limiting.py`.
That file has a legitimate, documented reason to do something unusual —
slowapi's rate limiter reads a `TESTING` environment variable at
*import time* to decide whether it's active at all, and every other
test file wants it OFF (hammering an endpoint in a tight test loop
isn't a real abuse pattern worth tripping over). So this one file
flips `TESTING` on, and to make that take effect, it deletes `main`
and every `app.*` module from Python's `sys.modules` cache and
reimports them fresh — then does the same deletion again on its own
teardown, so the next test in the session gets a normal, un-rate-limited
reimport.

The bug was in what that reimport does to `conftest.py`'s shared
`client` fixture. That fixture overrides FastAPI's `get_db` dependency
so every test talks to its own isolated, temporary SQLite file instead
of the real database — but it was keyed to a `get_db` function
reference imported once, at module collection time, before any test
runs. Once `test_rate_limiting.py` forced a fresh reimport of
`app.db.session`, every route in the newly-reimported `main` was wired
to a *new* `get_db` function object — a different one, in memory,
than the stale reference `conftest.py` was still overriding. FastAPI's
dependency-override dict is keyed by exact object identity, not by
name, so the override silently stopped matching anything. Every test
that ran afterward kept working — no error, no crash — while quietly
writing into the real `backend/database.db` file instead of its own
disposable one.

That's what made it invisible for as long as it was: a leak with no
symptom, right up until a test happened to check for state that a leak
would actually corrupt. Two of this session's new tests did exactly
that — checking that a second signup can't reuse an email already
taken — and got tripped up by a row that had genuinely, accidentally
persisted from an earlier, unrelated test run days before, sitting in
a real file on disk the whole time.

The fix was small once found: re-fetch `get_db` from `app.db.session`
*inside* the `client` fixture, every time it runs, instead of trusting
a reference captured once before any module-reloading trickery could
have made it stale. The real lesson is closer to last session's
route-ordering bug than it might look: something that reads as pure
infrastructure — a shared pytest fixture nobody was actively
editing — can still be quietly wrong in a way that only a new test,
checking something nobody had checked before, will ever surface. "This
file didn't change" is not the same claim as "this file's behavior
didn't change" when anything upstream of it did.

---

## Session: Rest of Group 2 — Delivery Lifecycle Completion

**Scope:** failed-delivery reason codes (CRUD + enforcement),
delivery-attempts logging, reschedule workflow, partial-delivery
marking, priority-based dispatcher-queue sorting — the remaining
delivery-lifecycle work after the core CRUD/offline-sync/dispatcher
console had already shipped.

**Design decision worth remembering:** `DeliveryPriority` is a plain
`String` column on `DeliveryRecordDB`, not a `SqlEnum` like `status`.
The reason is specific to this project's migration approach:
`db/migrate.py` only ever ADDs new columns to an existing SQLite
table, it never alters a column's constraints. SQLAlchemy's `Enum`
type on SQLite renders as a `CHECK` constraint baked with whatever
values existed at table-creation time — so if `status` had gained a
new enum value the same way `priority` was added, any database file
created before that value existed would reject it outright. Rather
than touch that risk at all, the reschedule workflow reuses the
existing `failed_attempt` status (a rescheduled delivery genuinely
hasn't been delivered yet) instead of adding a `rescheduled` status
value, and partial delivery is a boolean flag on top of `delivered`
rather than a new status. `priority`, `attempt_count`, and the
reschedule/partial fields are all new *columns* (safe, additive) with
validation happening at the Pydantic layer instead of the DB layer.

**Offline sync trade-off:** the online `PATCH /deliveries/{id}` path
hard-rejects a `failed_attempt` update missing a valid reason code
(400). The offline `/sync` path does not — `/sync` is intentionally
unauthenticated and processes a whole batch of an agent's queued
changes at once; rejecting a record over a missing reason code would
strand it retrying forever with no way for the agent to fix it until
they're back online and using the enforced path anyway. The attempt
is still logged either way, just without a reason code if one wasn't
present — a visible gap for a dispatcher to notice, rather than lost
data or a permanently-stuck sync queue.

No new bugs surfaced this session — the existing 100-test suite
passed unchanged throughout, and all 21 new tests (reason-code CRUD,
enforcement, attempt logging, reschedule, partial marking, priority
sorting, and the offline-sync threading test) passed on first
correct implementation after the initial route-registration fix.

---

## Session: Phase 11 — Fleet Management

**A stray reference from an earlier draft that broke every route on
import.** While writing `services/fleet.py`, an early version of the
utilization query referenced a model class named `DeliveryDB`. The
project's actual delivery model is called `DeliveryRecordDB`
(`models/delivery.py`) — `DeliveryDB` has never existed in this
codebase. Because `main.py` imports every route module (including the
new `routes/fleet.py`, which imports `services/fleet.py`) at process
start, this single bad name turned into an `ImportError` that broke
the entire app on startup, not just the one function — `pytest`
failed at collection time with every test file reporting the same
import error, before a single test could run. Fixed by correcting both
references to `DeliveryRecordDB` in `services/fleet.py`. Caught
immediately by running the new test file before assuming anything
worked, which is exactly the point of running tests before declaring
a feature done rather than after.

**Design decision — vehicle location is derived, not stored.** It
would have been easy to add `current_latitude`/`current_longitude`
columns directly to `VehicleDB` and update them wherever an agent's
location is updated. That was deliberately rejected: it would create a
second, independently-updated copy of the same fact ("where is this
agent right now") that the existing `AgentLocationDB` table (Phase 9)
already tracks — two copies that could silently drift apart if one
write path is ever missed. Instead, `GET /fleet/vehicles/{id}/location`
looks up the vehicle's `assigned_agent_id` and reads its live position
from the existing table on request. One source of truth, no sync risk.

Full backend suite after this session: **276/276 passing** (263 → 276,
13 new). Frontend `npm run build` clean.

---

## Session: Phase 12 — Customer Support

**Getting `org_id` right for a ticket with no delivery attached.** A
support ticket needs an `org_id` for tenant isolation, but unlike most
records in this project, a ticket isn't always created from something
that already has one in scope — a customer might file a general
account question with no order or delivery reference at all. The
naive fix (trust an `org_id` the client sends) was rejected outright:
it would let a customer claim membership in any org's queue. Instead,
`org_id` is always derived server-side — from the referenced order,
the referenced delivery, or (when neither is given) the customer's own
most recent order — so there's no code path where a client-supplied
org value is ever used.

**Reusing, not reinventing, file upload validation.** Ticket
attachments needed the same shape of validation `routes/products.py`
already has (allowed MIME types, a size cap, reject-empty-file) for
product images. Rather than writing a second, slightly-different
version of that logic, `routes/support.py` copies the same constants
and validation flow, saving to a separate `uploads/support/` directory
so the two upload types never collide on disk.

Full backend suite after this session: **289/289 passing** (276 → 289,
13 new). Frontend `npm run build` clean.

---

## Session: Phase 13 — Invoicing & Finance

**One table instead of five.** The spec listed invoice, receipt,
refund receipt, credit note, and debit note as separate features.
Modeling each as its own SQLAlchemy table would have meant five
schemas that are, structurally, the exact same thing: an amount
snapshot, tied to an order, with a sequential number and a
document-type-specific label. Built one `FinancialDocumentDB` table
with a `document_type` column instead — same "reuse the existing
shape, don't duplicate the concept" instruction this project's schema
already follows everywhere else (e.g. Phase 11's vehicle location
reusing Phase 9's agent-location table instead of a second one).

**Hooking into two existing flows instead of adding a manual step.**
An invoice or credit note that a dispatcher has to remember to
generate by hand will eventually not get generated. Instead,
`auto_generate_invoice_for_order()` is called directly inside
`routes/checkout.py`'s `verify_payment()` right after `order.status =
OrderStatus.paid`, and `auto_generate_credit_note_for_refund()` is
called directly inside `services/refund.py` right after each of its
two `log_ledger_entry(..., "refund", ...)` calls (test-mode and real
Razorpay paths both needed the hook, not just one). Both are
idempotent-safe: invoice generation checks for an existing invoice on
that order first, so even if this function were ever called twice for
the same order, only one invoice would exist.

Full backend suite after this session: **301/301 passing** (289 → 301,
12 new). Frontend `npm run build` clean.

---

## Session: Phase 14 — Public API & Webhooks

**Queue, don't send.** The first draft of `emit_event()` was tempted
to just call `attempt_delivery()` synchronously right there — simpler,
one function does the whole job. Rejected immediately: `emit_event()`
is called from inside `routes/checkout.py`'s `verify_payment()`,
`services/refund.py`, and `routes/deliveries.py`'s core status-update
path — if a subscribed webhook URL were slow or unreachable, a
synchronous send would make an unrelated customer's checkout or
refund hang or fail on network conditions it has nothing to do with.
`emit_event()` only ever creates a `WebhookDeliveryDB` row with
`status="pending"`; a separate background scheduler (services/
webhook_scheduler.py) does the actual sending on its own schedule,
completely decoupled from the request that triggered it.

**Full-suite runtime crossed a tool ceiling, not a correctness
ceiling.** Adding a fourth background scheduler (subscription, SLA
monitor, reminder, now webhook) pushed the combined 317-test run past
this environment's execution-time limit for a single command. Rather
than treating that as a pass, the suite was split into two batches by
file and both were run to completion and confirmed green (152 + 165 =
317 passed) before this phase was called done — a tool-imposed limit
on how long one command may run is not the same thing as "verified,"
and a batched-but-actually-run confirmation was worth the two extra
commands.

Full backend suite after this session: **317/317 passing** (301 → 317,
16 new; confirmed via two batched runs). Frontend `npm run build`
clean.

---

## Session: Phase 15 — Advanced Analytics

**A bug caught by the test, not assumed away.** The first version of
`profit_margin_analytics()` summed EVERY line item's revenue, but only
added a line's cost when its product had a `cost_price` set — meaning
a product with no cost on record would still count its full revenue
while contributing nothing to cost, silently overstating the margin.
`test_profit_margin_excludes_products_without_cost_price` caught this
immediately: it expected a ₹150 order (one ₹100 item WITH a cost
price, one ₹50 item without) to report ₹100 revenue, not ₹150. Fixed
by excluding a line from BOTH sides of the calculation when its
product has no `cost_price` — revenue and cost now always come from
the same subset of items, so the margin percentage is never distorted
by mixing priced and unpriced lines.

**Checked for duplication before writing anything.** Before designing
this phase, existing analytics-shaped endpoints were searched first —
SLA analytics (routes/sla.py), route efficiency/heatmaps
(routes/route_analytics.py), RTO analytics (routes/rto.py), support
analytics (routes/support.py), fleet utilization (routes/fleet.py) —
and the new endpoint was scoped to add only what none of those already
covered (agent-level productivity, failure-reason breakdown, retention,
category/payment-method revenue, margin, trend), rather than building
a second, overlapping "advanced" version of reports that already exist.

Full backend suite after this session: **327/327 passing** (317 → 327,
10 new; confirmed via two batched runs). Frontend `npm run build`
clean.

---

## Session: Phase 16 — Enterprise Organization Management

**Naming the actual limits of "suspension" instead of implying more.**
The spec's phrase "organization suspension" reads like a platform
operator taking a tenant offline from outside. This project has no
such role — every admin is scoped to exactly one org, by design, for
tenant isolation. Rather than either skipping the feature or quietly
building something that doesn't match its name, `suspend_organization()`
is a genuine self-service "pause operations" toggle, and its docstring
says exactly that: what it blocks (storefront listing, new signups,
new checkout) and what it deliberately does NOT block (existing staff
access — an admin needs to be able to reactivate their own org, which
a total lockout would prevent). Better to scope a feature honestly to
what the architecture actually supports than to name it grandly and
under-deliver.

**Same reuse-check discipline as Phase 15.** Before writing
routes/organization.py, the existing org-settings surfaces were
checked first (POD rules in routes/pod.py, SLA policies in
routes/sla.py, zones in routes/zones.py, pricing/visibility/slots in
routes/products.py's store_router) so this phase adds exactly the
missing pieces — branding, locale, usage, suspension, export — instead
of a second, overlapping settings system.

Full backend suite after this session: **339/339 passing** (327 → 339,
12 new; confirmed via two batched runs). Frontend `npm run build`
clean.

---

## Session: Phase 17 — Security & Session Management

**A NameError caught before it ever reached a test.** After adding the
new `/auth/sessions` endpoint with `response_model=List[SessionOut]`,
the very first sanity check — `python -c "import main"` — failed
immediately with `NameError: name 'List' is not defined`. `typing.List`
had never been imported into `routes/auth.py` before this phase. Fixed
in one line. This is exactly why the workflow here always runs the
import check before writing a single test: a broken import crashes
EVERY route in the app at process start, not just the new one, and
catching that before test collection even begins is far cheaper than
debugging a wall of unrelated-looking test failures.

**A second self-inflicted bug from careless editing.** While drafting
the recovery-codes-regenerate endpoint, a stray walrus-operator
fragment (`if not user.totp_enabled if (user := current_user) else
True: pass`) got left in from an editing mistake — dead, confusing,
and pointless code that the very next line already handled correctly.
Caught on a re-read before running anything, and removed. Worth noting
plainly: this wasn't a subtle logic bug, it was sloppiness, and it's
the kind of thing a second look catches before a reviewer (or a test
failure) has to.

**Reused RefreshTokenDB instead of inventing a session table.** The
spec asked for "active sessions" and "session/device information" as
if they were a new concept. They aren't, in this codebase —
`RefreshTokenDB` already IS the durable server-side session record
(Phase: refresh-token rotation with theft detection). Adding
`device_info`/`ip_address` columns to it and filtering to
not-revoked/not-expired rows was the entire "Active Sessions" feature.
A parallel `SessionDB` table would have meant two systems that could
drift out of sync about which sessions are actually valid.

Full backend suite after this session: **352/352 passing** (339 → 352,
13 new; confirmed via three batched runs). Frontend `npm run build`
clean.

---

## Session: Phase 18 — Monitoring & Reliability (final phase)

**Extending an existing middleware instead of stacking a new one.**
`main.py` already had a single `@app.middleware("http")` wrapping
every request to add security headers and catch unhandled exceptions
into a generic 500 response. Rather than adding a SECOND middleware
just for request timing and error logging, the existing one was
extended in place — one `time.monotonic()` call at the top, one
`monitoring_svc.record_api_request()` call on both the success and
exception paths, and one `monitoring_svc.record_error()` call added to
the exception branch that already existed. Two middlewares doing
related work on every request would have meant two places to reason
about request/response mutation order for no real benefit.

**In-memory metrics were a deliberate choice, not a shortcut.** The
instinct when asked for "API performance monitoring" is to reach for a
database table logging every request. That would mean a write on
every single API call — real cost, for data that only matters for the
current process's uptime and that nobody needs to query historically
across restarts. `API_METRICS`/`NOTIFICATION_METRICS` in
`services/monitoring.py` are plain in-memory dicts behind a lock,
explicitly documented as answering "is something wrong right now," not
an audit trail — the same reasoning that led `ErrorLogDB` and
`JobHeartbeatDB` (which genuinely need to survive a restart to be
useful) to be actual tables while these didn't need to be.

**An honest "not applicable" beats a fake "success."** `create_backup()`
checks `IS_SQLITE` first and, for a PostgreSQL deployment, returns a
plain explanation that this endpoint can't back up a database it has
no file-level access to — rather than either crashing unhelpfully or,
worse, returning a "success" response that silently backed up nothing.
This is the same pattern already established for Phase 16's honestly-
scoped organization suspension and Phase 14's OAuth/SSO skip: naming
an actual limitation plainly is worth more than a response that looks
complete but isn't.

Full backend suite after this session — **the final phase**:
**367/367 passing** (352 → 367, 15 new; confirmed via three batched
runs). Frontend `npm run build` clean.

---

## Post-launch polish: password visibility, dispatcher return-to-pool, motion

No real bugs this session — a clean feature/design pass after the
18-phase rollout finished. Worth noting for the record: the new
per-row "Reassign" dropdown deliberately does **not** duplicate the
bulk-assign-agent backend logic — it calls the exact same
`PATCH /deliveries/bulk-assign-agent` endpoint with a single-item
`delivery_ids` array, so a single-row reassign gets the same
tested history/notification/status-transition behavior as a bulk
one for free, with zero new backend branching to get wrong. The
genuinely new endpoint, `return-to-pool`, was scoped narrowly on
purpose: it only accepts a customer-placed order still in the
`picked_up` "just assigned, not yet touched" state, matching the
same restriction `assign_agent_to_delivery` already applies for the
same reason (a manually created delivery has no unassigned pool to
return to; once a package is `out_for_delivery` returning it to a
pool would just be confusing, not useful).

Full backend suite after this session: **373/373 passing** (367 → 373,
6 new; confirmed via three batched runs, same reasoning as every
batched run since Phase 14 — the full suite exceeds this environment's
single-command execution-time ceiling). Frontend `npm run build`
clean.

---

## Diagnosing a batching artifact in test_api_metrics_recorded_across_requests

Not a real bug, but worth recording since it looked like one at first.
While re-verifying the full suite after the OAuth/code-splitting/
Postgres-backup session, `test_monitoring.py::
test_api_metrics_recorded_across_requests` failed when run in a batch
that happened to put `test_finance.py` and `test_fleet.py` immediately
before `test_monitoring.py` in the same `pytest` process — but passed
every time in isolation.

Root cause: `services/monitoring.py`'s `API_METRICS` is a deliberate
module-level, process-lifetime in-memory dict (see that file's own
docstring — resets on restart, no DB write per request, single-process
deployment assumption), and `get_api_metrics_summary()`'s
`slowest_endpoints` is capped to the top 15 by duration. `GET /health`
is about as fast as an endpoint gets, so once ~15+ *other*, naturally
slower endpoints have been exercised earlier in the *same pytest
process*, it falls out of that capped list — the test's assertion that
`GET /health` appears in `slowest_endpoints` is really an assertion
about how much unrelated traffic happened to run first in that
process, which was never guaranteed. Confirmed by re-running with the
project's already-established batch boundaries (which happen to keep
fewer distinct endpoints in front of `test_monitoring.py` per batch)
— passes cleanly, 393/393.

Left as-is rather than "fixed" in this session: rewriting the test to
not depend on ranking position, or resetting `API_METRICS` per test,
are both reasonable but out of scope for what was actually asked this
session (OAuth/code-splitting/Postgres-backups) — noted here so a
future session doesn't have to re-diagnose it from scratch if it
resurfaces in a different batch split or in CI's single full-suite run
(where finance/fleet already precede monitoring alphabetically).

---

## Real bug caught before shipping: shared OAuth redirect_uri between staff and customer flows

While adding customer-facing Google OAuth (mirroring the staff flow
from the previous session), `services/oauth.py` still had a single
module-level `GOOGLE_REDIRECT_URI` constant baked directly into
`build_authorization_url()` and `exchange_code_for_profile()`. That
was fine when only one flow (staff) existed. Once the customer
callback route (`/customer/oauth/google/callback`) was added at a
different path than the staff one (`/auth/oauth/google/callback`),
reusing the same constant for both meant every customer "Sign in with
Google" click would have told Google to redirect back to the STAFF
callback instead — the state token's claim shape wouldn't match
what that route expects, and the sign-in would fail outright in any
real deployment.

This did not fail any test on the first pass, because every OAuth
test in this project (staff and customer) calls the callback function
directly with a `state` value obtained from the corresponding
`/oauth/google/login` endpoint — it never exercises Google's own
server-side check that the token-exchange request's `redirect_uri`
matches the one originally used to obtain the authorization code.
That check only happens on Google's side during a real round-trip,
which nothing in this test suite performs (nor should it — hitting
Google's real OAuth endpoints from a test suite would be flaky,
slow, and require real credentials).

Caught by re-reading the new customer routes against the shared
`services/oauth.py` module before considering the feature done, not
by a failing test. Fixed by parameterizing `redirect_uri` as an
explicit argument on both functions, with a new
`GOOGLE_CUSTOMER_REDIRECT_URI` derived from the staff one (string
substitution, not a second env var — one thing to configure, not two
that could drift out of sync). Added a regression test asserting the
two authorization URLs actually carry different `redirect_uri` query
values, since that's the one thing the rest of the OAuth test suite
structurally cannot catch on its own.

**Lesson for future OAuth/multi-flow work in this project**: any
shared helper module serving more than one caller with per-flow
identity (redirect URIs, callback paths, audience claims) needs an
explicit test asserting the two callers actually diverge where they
must — "both flows pass their own tests independently" does not
catch "both flows accidentally use the same hardcoded value for
something that needs to differ."

---

## Bug caught before shipping: shared redirect_uri would have broken customer OAuth in production

While building customer-facing Google OAuth as a direct extension of
the staff flow from the previous session, `services/oauth.py`'s
`build_authorization_url()` and `exchange_code_for_profile()` both
still referenced a single module-level `GOOGLE_REDIRECT_URI` —
correct for staff (`/auth/oauth/google/callback`), but silently wrong
for customer sign-in, which needs Google to redirect to
`/customer/oauth/google/callback` instead. Left as-is, every real
customer Google sign-in attempt would have redirected to the STAFF
callback route, where the state token's claim shape wouldn't match
(`customer_oauth_provider` vs `oauth_provider`) and the sign-in would
fail with a generic "this sign-in attempt has expired" error — no
crash, no obvious stack trace, just a broken feature that looked
superficially fine.

It looked fine specifically because every test written for this
flow calls the callback function directly with a `code`/`state`,
bypassing the part of the OAuth2 spec that would have caught it:
Google itself validates that the `redirect_uri` on the token-exchange
request matches the one originally used to obtain the authorization
code, and a mismatch there is invisible to a test that never talks to
the real Google endpoints (see test_customer_oauth.py's own module
docstring on why that's the deliberate seam).

Caught by re-reading the diff before considering the feature done,
not by a test failing — worth noting as a case where "all tests pass"
and "the feature actually works" are different claims when the thing
under test is a redirect-based protocol whose correctness partly
lives in what a THIRD PARTY (Google) will accept, not just in this
codebase's own logic. Fixed by parameterizing `redirect_uri` on both
functions and adding a `GOOGLE_CUSTOMER_REDIRECT_URI` derived from the
staff one; also added a regression test that inspects the actual
`redirect_uri` query param on both flows' authorization URLs and
asserts they differ, so this specific mistake can't silently
reappear.

---

## Wrong tool gave misleading errors while verifying the new mobile app

While validating the new `mobile/` Expo app's source files, `npx babel
App.js --presets babel-preset-expo` resolved to `babel@5.8.38` — a
long-abandoned, decade-old standalone package literally named `babel`
on npm, not the modern `@babel/cli`. Its CLI flag parsing is completely
different from the modern toolchain, so it produced confusing
`TypeError [ERR_INVALID_ARG_TYPE]: The "path" argument must be of type
string` errors on every file, and outright JSX syntax errors on the two
files with the most JSX. None of that reflected a real problem with the
source files.

Caught before treating any of those results as real, by noticing the
error shape didn't match a plausible JSX/syntax issue and checking
which package actually got resolved. Fixed by writing a small script
that requires `@babel/core` directly (the same package `babel-preset-
expo` itself depends on, already installed via the project's own
`npm install`) and calls `babel.transform()` with the project's real
preset — the same code path Metro (Expo's actual bundler) itself would
use — which correctly compiled all 10 files with zero errors, real
validation this time.

Worth recording as a general caution: `npx <name>` silently fetching
and running whatever unrelated package happens to occupy that exact
name on npm (rather than the intended `@scope/name` or `name-cli`
tool) is a real, general npx footgun — not specific to Babel, and
worth double-checking the resolved package/version before trusting a
tool's output, especially when a command that should be routine
produces errors that don't make sense for the input.

---

## Real accessibility bug found by writing a test, not by an audit

While writing `LoginPage.test.jsx` (see `docs/FEATURE_LOG.md`'s entry
for the new frontend test suite), `screen.getByLabelText(/username/i)`
failed to find the username input at all — despite the label
"Username" being right there, visibly, immediately above the field in
the rendered page.

The cause: `LoginPage.jsx`'s labels were plain `<label>Username</label>`
elements with no `htmlFor`, and the inputs had no matching `id` — so
there was no actual programmatic association between them, only
visual proximity. A sighted user reading the page has no way to tell
the difference; a screen reader does, since `getByLabelText` uses the
exact same accessibility-tree lookup a screen reader relies on to
announce which label goes with which field. This is precisely the
class of bug an accessibility audit exists to catch, found instead as
a side effect of writing an ordinary component test — worth noting as
a real, concrete reason "add tests" and "add an accessibility pass"
aren't as separate as they might sound; a test written the way React
Testing Library encourages (query by role/label, not by CSS selector
or test-id) inherently exercises some of the same accessibility tree
a screen reader does.

Fixed by adding `id`/`htmlFor` pairs to every label/input pair in
`LoginPage.jsx` (the account-type select, the username/email field,
the password field, the 2FA code field) rather than loosening the
test to `document.querySelector` its way around the gap — the fix
belongs in the component, since the underlying accessibility problem
is real regardless of whether a test happens to be looking for it.

This was found in exactly one component (`LoginPage.jsx`) because
that's the one component with a test written against it this session —
it's a reasonable bet the same `<label>` (no `htmlFor`)/`<input>` (no
`id`) pattern recurs in some of the other ~62 components that still
have no tests, not something to assume is isolated to this one file.
A genuine accessibility audit across the whole frontend (keyboard
navigation, ARIA roles, color contrast, screen-reader announcements —
not just label association) remains a real, separate, not-yet-done
piece of work — noted here rather than implied to be covered by this
session's test suite.

**That bet paid off.** A few sessions later, while doing a general
improvement pass, grepping the codebase for the same bare
`<label>text</label>` (no `htmlFor`) pattern found it recurring in
`SignupPage.jsx`, `ForgotPasswordPage.jsx`, and `ResetPasswordPage.jsx`
— every field on all three (role selector, name/email/password on both
the customer and staff signup forms, the invite-code/org-name fields,
the forgot-password email field, both reset-password fields) had the
identical `<label>`-with-no-`htmlFor` bug, unrelated to and undetected
by the fix above since no tests existed for any of those three files
yet. Fixed the same way: `id`/`htmlFor` pairs added to every field
(disambiguated per-form where a customer and a staff form share a
label like "Email" or "Password" on the same page), then a new test
file per component (`SignupPage.test.jsx`, `ForgotPasswordPage.test.jsx`,
`ResetPasswordPage.test.jsx`) written the same `getByLabelText`-first
way, so the fix is locked in rather than just visually verified.

The same grep also turned up this exact pattern in 11 *other*
components outside the auth flow (`AccountSettings.jsx`,
`AuditLogViewer.jsx`, `CustomerDashboard.jsx`,
`FailedDeliveryReasonManager.jsx`, `MyWorkforce.jsx`,
`ProductManager.jsx`, `Storefront.jsx`, `SubscriptionManager.jsx`,
`TwoFactorSettings.jsx`, `WorkforceManager.jsx`, `ZoneManager.jsx` —
roughly 80 more unlabeled fields combined). Those were deliberately
**not** fixed in this pass — the auth pages were fixed because they
were the ones already being touched (password-reset deep-linking) and
because they're the highest-traffic, first-impression forms in the
app; sweeping all 11 remaining files is real, additional, not-yet-done
work, stated plainly here rather than implied to be finished by this
entry. If picked up later: same mechanical fix (an `id` per input, a
matching `htmlFor` per label), plus a test per component so it can't
silently regress again.

---

## Two real snags while adding the mobile offline queue's test suite

**Peer dependency conflict on first install.** Adding
`@testing-library/react-native` to `mobile/package.json` for component
tests failed `npm install` outright: the latest version pulled a
transitive `react-test-renderer@19.2.8` expecting React 19, while this
project pins `react@18.2.0` (matching the Expo SDK 51 / React Native
0.74 versions everything else here is built against). Rather than
forcing it through with `--legacy-peer-deps` (which would silently
paper over a real version mismatch that could bite later), reconsidered
what was actually needed: the planned tests were for
`offlineStore.js`/`offlineSync.js` — pure logic and AsyncStorage/
network mocking, not component rendering — so `@testing-library/
react-native` wasn't actually required for this session's tests at
all. Dropped it; `jest` + `jest-expo` alone installed cleanly and were
sufficient. Left as a clearly-named gap for later (mobile screen
components have no tests yet — see `mobile/README.md`'s "Running
Tests" section) rather than forced through with a mismatched
dependency tree just to have something installed.

**A timer-contamination bug in a test I wrote, not in the app.** An
early version of `offlineSync.test.js`'s "does not trigger a sync when
the app goes to background" test called
`jest.runOnlyPendingTimersAsync()` after simulating the background
AppState event — which also let the independent 15-second periodic-
sync `setInterval` fire, since it counts as "pending" too. The test
failed, and it initially looked like a real bug (the periodic sync
firing when it shouldn't) before checking more carefully: the periodic
sync running on its own schedule regardless of foreground/background
state is neither a bug nor was it a bug I was even testing for — this
test cared specifically about whether backgrounding, by itself,
triggers an extra sync. Fixed by flushing only microtasks
(`await Promise.resolve()` twice) for that one assertion instead of
running pending timers, isolating exactly the thing being tested.

---

## A generated-data bug caught by looking at the output, not just the exit code

While building the demo seed script (`services/demo_seed.py`), the
first working version ran without any exception and produced the
right row counts — every table populated, every delivery status
represented, looked done. It wasn't: printing the actual SLA-status
distribution for a sanity check showed `Counter({'missed': 24,
'breached': 10, 'not_applicable': 7, 'on_track': 3, 'met': 2})` — a
demo where the vast majority of completed deliveries appear to have
missed their deadline, which is both an unrealistic story for a
"here's a well-run operation" demo and, more importantly, a sign
something was actually wrong rather than just unlucky random data.

The cause: `_compute_sla_status()`'s `delivered` branch compared the
delivery's `expected_by` deadline against `now` (the current
wall-clock time, captured once when the whole seed script starts) to
decide "met" vs "missed" — but the right comparison for a delivery
that's ALREADY DELIVERED is against WHEN IT WAS ACTUALLY DELIVERED,
not against whatever moment the seed script happens to run. Since the
seeded deliveries span up to 13 days in the past, `expected_by` was
almost always earlier than "right now" regardless of how promptly the
delivery was actually completed — so nearly everything read as
"missed" by construction, independent of the (separately, correctly
randomized) actual on-time/late split the code was trying to
represent.

Fixed by passing the delivery's own `updated_at` (its completion
timestamp) into the comparison instead of `now`, and adding a
regression test (`test_delivered_orders_mostly_meet_their_sla_not_
mostly_miss_it` in `tests/test_demo_login.py`) asserting a healthy
majority of seeded deliveries show "met" — a test that would have
caught this bug immediately, and now guards against it recurring.
Worth recording as a general pattern: a script that creates its own
test data can pass every structural check (right row counts, no
exceptions, every enum value represented) while still being
substantively wrong in a way only inspecting the actual generated
values — not just whether generation completed — would catch.

---

## Web Push had been silently broken this project's entire history — found while adding Expo push

While building `services/expo_push.py` (the mobile app's push
notification channel), the plan was to reuse `services/push.py`'s Web
Push as a reference implementation to mirror. Reading it closely
before writing anything new turned up something worth checking: its
`send_web_push()` function referenced `monitoring_svc` in both its
success and failure branches, but the file never imported it anywhere.

Confirmed by actually calling the function directly (not just reading
the code) that this was real, not a false alarm: every call raised a
bare `NameError`. Checked why this had never been caught by the
existing 425+ backend tests — `send_web_push` is only ever reached
once a genuine `PushSubscriptionDB` row exists for the target user or
customer (see `_push_to_user_ids`/`_push_to_customer` in
`services/notifications.py`), and nothing in the test suite had ever
created one before this session. **Every real Web Push send in this
project's history would have crashed at this line, silently** (the
crash happens inside a bare function call with no test or endpoint
depending on its return value failing loudly) — a customer or agent
who enabled push notifications would simply never have received one,
with no error visible anywhere in the product itself.

Fixed the import, then re-ran the same direct call to confirm the fix
— and hit a SECOND, unrelated `ValueError` immediately, from deep
inside the `cryptography` library, before the fix could even be
verified. Traced it rather than assuming it was a new problem caused
by the import fix: the checked-in default VAPID private key is a full
PEM string (`-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE
KEY-----`), and `pywebpush`'s `vapid_private_key` parameter — when
given a plain string rather than a `Vapid` object — hands it to
`py_vapid.Vapid.from_string()`, which does `private_key.encode().
replace(b"\n", b"")` and treats the ENTIRE remaining string (headers
included) as base64 to decode. It does not strip PEM armor. Confirmed
by loading the same PEM directly via `cryptography.hazmat.primitives.
serialization.load_pem_private_key()` (works fine — the key itself was
never invalid) and separately via `py_vapid.Vapid01.from_pem()` (which
DOES strip the header/footer lines before decoding, and also worked)
— isolating the bug to "wrong py_vapid entry point for this input
shape," not "bad key" or "bad library version." **This means Web Push
had actually never worked in this project at all, at any point** — the
import bug alone would have been enough to break it, and this VAPID
format bug was a second, independent way it was already broken
underneath that.

Fixed by constructing a real `Vapid01` object once at module load via
`Vapid01.from_pem()` and passing that object (not the raw PEM string)
to `webpush()` — the code path `pywebpush`'s own `isinstance(vapid_
private_key, Vapid01)` check exists to support. Verified via the same
direct call one more time: it got past both prior failures and made
an actual HTTP POST attempt to the (deliberately fake, unreachable)
test endpoint — which surfaced a THIRD gap on the same call: a
`requests.exceptions.ConnectionError` from the real network attempt
wasn't caught by the original `except WebPushException` clause,
violating the function's own documented "never raises" promise.
Broadened to catch generally, and confirmed clean on a fourth attempt.

Three real bugs, each one hidden behind the previous one, each only
found by actually calling the function end-to-end and reading what it
literally did next rather than stopping once the first fix seemed to
resolve the visible symptom. Locked in with 4 regression tests in the
new `tests/test_web_push.py` — see `docs/FEATURE_LOG.md`'s entry for
the full list.

---

## Two design mistakes caught during review, before either shipped

While wiring `ProofOfDeliveryScreen.js` and `FailedAttemptScreen.js` to
navigate back to `DeliveryDetailScreen.js` after a successful update,
the first version threaded the just-updated delivery record through
as an extra navigation param (`justUpdated`) so the detail screen
could show it immediately without a re-fetch. Re-reading
`DeliveryDetailScreen.js` before finishing turned up why this was
unnecessary complexity, not a real optimization: that screen already
has a `useFocusEffect` that re-fetches the delivery from the server
(or cache) every time the screen regains focus — which is exactly what
happens when navigating back to it from either of the two new screens.
The `justUpdated` param would have been dead weight at best, and a
source of subtly-stale-UI bugs at worst if React Navigation ever
reused the existing screen instance in a way that didn't cleanly
overwrite the param. Removed before ever running it, in favor of just
letting the existing re-fetch do its job.

Separately, `sendDeliveryMessage(deliveryId, body)` was first written
sending `{ body: message }` as the request payload — a natural-enough
field name for "the message's body" that turned out to be wrong: the
backend's actual `MessageCreate` schema (`backend/app/models/
delivery_message.py`) expects `{ message: "..." }`. Caught by checking
the backend model directly instead of assuming the guessed name was
right, before writing a single test against it — and then a test
(`api.test.js`'s "sends a message with the correct field name (message,
not body)") was written specifically to lock in the correct shape,
since this is exactly the kind of easy-to-get-wrong, easy-to-not-notice
mistake (the request would still LOOK like it succeeded from a naive
glance at the code, and would only visibly fail once a real message
actually needed to reach the backend).

Neither of these was a bug that shipped and got caught later — both
were caught by re-reading the code and the backend model before
considering the feature done, which is the cheaper time to catch
either kind of mistake.

---

## Why This Log Matters

Every issue logged above is a genuine, realistic bug — not something
contrived for practice. Being able to explain any of them in an interview
(what happened, why, and how it was diagnosed and fixed) is a much
stronger signal of real understanding than simply saying "the project
works." Recruiters and interviewers responding to a portfolio project
often ask "what was the hardest bug you ran into building this?" — this
document is meant to make that question easy to answer in detail, using
your own words, at any point in the future.
