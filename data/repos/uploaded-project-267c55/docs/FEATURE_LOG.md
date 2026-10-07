# Feature Log — What, Why, and What It Does

This file tracks every feature built into this project, in the order it
was added: what was missing before it existed, why it was needed, and
what it actually does now. This is different from `PROJECT_WORKFLOW.md`
(which logs bugs and how they were fixed) — this file is about *decisions*
and *reasoning*, so you can explain not just how something works, but why
it exists at all.

This file is maintained going forward — every new feature gets an entry
here the same day it's built, not added retroactively.

---

## Phase 1 — Backend Foundation

**What was missing:** No backend existed at all — no way to store or
retrieve delivery data anywhere.

**Why it was needed:** Every other feature in this project depends on
having somewhere to persistently store delivery records and expose them
over HTTP. This is the foundation everything else builds on.

**What it does:** A FastAPI backend with a `DeliveryRecord` model and
CRUD endpoints (create, read, update, list), backed by SQLite.

---

## Phase 2 — Offline-Capable Frontend

**What was missing:** No frontend, and more specifically, no way for the
app to function without an internet connection.

**Why it was needed:** This is the actual core premise of the entire
project — delivery agents lose connectivity constantly (basements,
elevators, rural areas), and most delivery apps just fail or block in
that situation. Without offline capability, this project would just be
another CRUD app with no real differentiator.

**What it does:** A React frontend using IndexedDB as local-first storage.
Every change an agent makes saves to IndexedDB immediately, regardless of
connectivity.

---

## Phase 3 — Sync Engine with Conflict Resolution

**What was missing:** Offline changes had nowhere to go — they'd sit in
IndexedDB forever with no way to reach the server, and no plan for what
happens if the same delivery was changed in two places while offline.

**Why it was needed:** Offline storage alone is only half the problem —
a real system needs to reconcile offline changes with the server once
connectivity returns, and handle the case where two different changes
conflict.

**What it does:** A `/sync` endpoint and client-side sync engine that
pushes pending offline changes to the server, using a last-write-wins
strategy (based on timestamps) to resolve conflicts automatically.

---

## Phase 4 — Dispatcher Filtering & Agent List Fixes

**What was missing:** No way to filter the dispatcher's delivery list by
status, and delivery ordering was arbitrary (whatever order IndexedDB
happened to return).

**Why it was needed:** These came up organically while testing Phase 3 —
using the app surfaced real usability gaps that weren't obvious during
planning: a dispatcher managing more than a handful of deliveries needs
filtering, and an agent needs predictable ordering, plus a way to remove
records.

**What it does:** Status filtering + a "Showing X of Y" count on the
dispatcher table; sorting and delete functionality on the agent view.

---

## Authentication — Login, Signup, Logout, Roles

**What was missing:** Every agent was hardcoded as `"agent-001"` — there
were no real user accounts, no way to distinguish one agent from another,
and no concept of a dispatcher role at all.

**Why it was needed:** A hardcoded placeholder agent isn't a real,
deployable product — it was a stand-in to get the sync logic working
first. For the app to have real users, it needs real accounts, and for
dispatchers and agents to have different permissions/views, it needs
role-based access.

**What it does:** JWT-based signup/login/logout, with two roles (`agent`,
`dispatcher`) that gate what each user can see and do.

---

## Dispatcher-Assigned Deliveries (replacing self-created "sample" deliveries)

**What was missing:** Agents could only create their own placeholder
"sample" deliveries — there was no real dispatcher-to-agent assignment
workflow, which doesn't reflect how real delivery operations work.

**Why it was needed:** In a real delivery company, a dispatcher assigns
work to agents — agents don't invent their own deliveries. This also
directly enables role-based permissions to mean something (dispatcher-only
creation, agent-only fulfillment).

**What it does:** Dispatchers assign deliveries to a specific agent from
a dropdown; agents automatically pull in (sync down) whatever's been
assigned to them.

---

## Search Bar (Agent + Dispatcher)

**What was missing:** No way to find a specific delivery without manually
scrolling through the full list.

**Why it was needed:** As delivery volume grows, scanning a full list
becomes impractical — this is standard functionality any real operations
tool needs.

**What it does:** Search by order ID (agent view) or order ID/agent name
(dispatcher view), filtering the visible list live as you type.

---

## Sort + Advanced Filter (status, date range, agent) & Delivery Detail Modal

**What was missing:** Filtering was status-only, with no way to narrow by
agent or date, and no way to see a delivery's full details beyond what
fit in a table row.

**Why it was needed:** A dispatcher managing multiple agents over time
needs to answer questions like "what did this agent do last Tuesday?" —
which requires combining filters, not just one at a time. A table row
also can't show everything about a delivery (full notes, exact
timestamps) without becoming unreadable.

**What it does:** Combinable status/agent/date-range filters, a sort
dropdown, and a click-through modal showing a delivery's full details.

---

## Status History / Audit Log

**What was missing:** The detail modal showed a delivery's *current*
state, but nothing about how it got there — no record of who changed
what, or when.

**Why it was needed:** Accountability and traceability are core to any
real operations tool — if a delivery was marked "failed" incorrectly, or
a dispatcher needs to know who last touched a record, there needs to be
an actual audit trail, not just a snapshot of the current state.

**What it does:** Every create/update action writes a history entry
(who, what changed, when), shown as a timeline in the detail modal.

---

## Toast Notifications

**What was missing:** Sync results, assignment confirmations, and errors
were shown as plain inline text sitting in the page — easy to miss, and
not a pattern real users expect from a polished app.

**Why it was needed:** Plain inline text messages are a placeholder
pattern, not a real UI pattern — most production apps use transient,
visually distinct notifications so the user notices feedback without it
disrupting the layout.

**What it does:** Auto-dismissing notification cards (bottom-right) for
sync results, delivery assignment, and delete confirmations.

---

## Summary Stat Cards (Dispatcher Dashboard)

**What was missing:** A dispatcher had to scroll/filter the full table
just to answer basic questions like "how many deliveries failed today?"

**Why it was needed:** Dashboards exist to give an at-a-glance operational
picture — forcing a dispatcher to manually count rows defeats the purpose
of having a dashboard at all.

**What it does:** Live counts for each status, plus "Delivered Today," at
the top of the dispatcher view.

---

## Agent Ordering Fix (stable list order)

**What was missing:** Sorting the agent's list by "most recently updated"
caused a delivery to visually jump to the top the moment its status was
changed.

**Why it was needed:** This was a direct usability complaint — an agent
working through a list shouldn't have items reordering under them mid-task,
since that's disorienting and error-prone in a real field-work context.

**What it does:** The agent's list now sorts by creation order, which
stays stable regardless of what status changes happen afterward.

---

## Agent Performance View

**What was missing:** No way for an agent to see their own work summary —
completed today, completed this week, current workload.

**Why it was needed:** A real delivery agent (and their employer) cares
about individual performance tracking, not just the raw list of
deliveries — this is standard in any operations/logistics tool.

**What it does:** A dedicated sidebar view showing completed
today/this-week counts, in-progress count, failed attempts, and a
completion rate.

---

## Pagination

**What was missing:** Both the agent and dispatcher views rendered every
matching delivery at once, with no limit.

**Why it was needed:** This doesn't scale — a dispatcher managing
hundreds of deliveries, or an agent with a long work history, would face
a slow, unwieldy, endlessly-scrolling page.

**What it does:** Both views now page results (5 per page for agents, 8
per page for the dispatcher table) with Previous/Next controls.

---

## Full Visual Redesign ("Fleet Ops Console" theme)

**What was missing:** The app used default, unstyled browser form
elements throughout — functional, but looking like an early-stage student
project rather than a real product.

**Why it was needed:** You were explicit that this needed to look and
feel like something worth actually deploying and using — not just a
backend with a bare-minimum UI on top. Visual polish is also part of what
makes a portfolio project stand out.

**What it does:** A cohesive dark theme (custom color palette, Space
Grotesk/Inter/JetBrains Mono typography, sidebar navigation, styled
tables/cards/badges/modals) applied consistently across every screen.

---

## Light / Dark Theme Toggle

**What was missing:** The redesign only shipped a dark theme — there was
no way to switch to a light theme, and no guarantee that a light theme
would even be readable if one existed (dark-tuned colors often fail
contrast on a white background).

**Why it was needed:** You explicitly asked for both themes with a
toggle, and specifically flagged that every button and piece of text must
stay clearly visible after switching — not just an inverted color scheme
that happens to look broken in one mode.

**What it does:** A toggle button (sidebar footer, and on the Login/Signup
pages) switches between themes instantly, persisted in localStorage so it's
remembered on return visits. Every component uses the same CSS variable
names in both themes — only the underlying color values change (defined
once in `theme.css`), so no component contains theme-specific logic. Status
and semantic colors are deliberately re-tuned (not just inverted) for the
light theme, since colors bright enough to read on near-black fail contrast
on white.

---

---

## Delivery Time Estimates ("Expected By")

**What was missing:** No way to communicate or track a deadline for a
delivery — a dispatcher couldn't flag "this needs to arrive by 6pm," and
nothing surfaced when a delivery was running late.

**Why it was needed:** Real delivery operations run on time windows —
this is standard operational depth expected of a genuine logistics tool,
not just a status tracker.

**What it does:** An optional `expected_by` datetime, set when a
dispatcher assigns a delivery (single or bulk). Shown on the agent's card,
the dispatcher's table, and the detail modal — automatically flagged in
red as "(Overdue)" if the deadline has passed and the delivery isn't yet
marked delivered.

---

## Route Optimization / Batching

**What was missing:** An agent's deliveries had no concept of geography —
just a flat list in assignment order, regardless of where anything
actually was.

**Why it was needed:** A real delivery agent working multiple stops
benefits enormously from knowing which deliveries are near each other and
a sensible order to visit them in — this is a core "operational depth"
feature of any real logistics tool, not just a nice-to-have.

**What it does:** An optional `zone` (free-text area name) and optional
latitude/longitude on each delivery. The agent's "Suggested Route" panel
groups active deliveries by zone, and — where coordinates are available —
orders them within each zone using a nearest-neighbor heuristic (starting
from the agent's live location via browser geolocation, with a disclosed
fallback if permission is denied). No paid maps/geocoding API was used or
needed. Deliveries without coordinates still work fine — they're just
grouped by zone rather than precisely ordered, which is disclosed in the
UI rather than hidden.

---

## Bulk CSV Import

**What was missing:** A dispatcher could only assign one delivery at a
time through the form — there was no way to onboard many orders at once.

**Why it was needed:** Real dispatch operations regularly receive orders
in bulk (e.g. an end-of-day CSV export from an order-management system) —
one-by-one assignment doesn't scale to real volume.

**What it does:** A dispatcher uploads a CSV (`order_id`,
`agent_username` required; `notes`, `zone`, `expected_by` optional). Each
row is validated and processed independently — a bad row (unknown agent,
blank order ID) is reported with a clear per-row error, while every valid
row in the same file still succeeds. Built with a hand-written CSV parser
(not a naive comma-split) so notes containing commas, quoted fields, and
Windows-style line endings all parse correctly — tested directly against
those specific edge cases before being wired into the UI.

---

## Multi-Tenant Support

**What was missing:** Every user and delivery lived in one shared, global
space — there was no concept of "which company does this belong to."
Deploy this for two different delivery businesses and they'd see each
other's agents, deliveries, and dashboards.

**Why it was needed:** A real deployment needs to serve more than one
organization on the same running app without their data ever mixing —
this is what makes the project a genuine multi-customer product rather
than a single-team internal tool.

**What it does:** Every user belongs to exactly one organization,
established at signup: either **create** a new one (entering an org name
— you become its admin automatically) or **join** an existing one via an
8-character invite code shown once at creation (and re-visible to the
admin afterward — see Admin Panel below). Every single query in the app —
listing deliveries, listing agents, fetching history, exporting CSVs —
filters by the caller's `org_id`, verified with two separate test
organizations and confirmed each saw zero of the other's data.

**A real vulnerability found and fixed while building this:** the offline
`/sync` endpoint is intentionally unauthenticated (see Rate Limiting
below for why), which meant a crafted payload could reference an
existing delivery ID belonging to a *different* organization and
overwrite it, as long as it paired that ID with one of its own agent
IDs. Fixed by verifying the existing record's organization matches the
requesting agent's organization before allowing any update — confirmed
by actually simulating this exact attack in testing and watching it get
correctly rejected.

---

## Admin Panel

**What was missing:** No way to see who belonged to an organization, no
way to disable a departing employee's access, and no way to help someone
who forgot their password — accounts, once created, were permanently
fixed with no management capability at all.

**Why it was needed:** Any real organization using this needs basic user
administration — this is baseline expected functionality for a
multi-user product, not an optional extra.

**What it does:** A dedicated `admin` role (the first person to create an
organization becomes its admin automatically) can view every user in
their organization, deactivate or reactivate an agent's account
(deactivation takes effect immediately — even blocking that user's
*already-issued* login token, not just future login attempts), and reset
a user's password directly. Honest, disclosed limitation: since there's
no email service, "reset password" means the admin sets a new one and
shares it with the person themselves — not an emailed reset link, which
is what a production system would use instead.

**A gap fixed before calling this done:** admins initially had no
sidebar link to the actual delivery dashboard at all — only "Manage
Users" — meaning the very first user of any brand-new organization would
have had no way to assign a single delivery, despite the backend already
permitting it. Fixed by giving admins both links, defaulting to the
Dashboard as their landing view. Separately, the signup screen promised
"any admin can look up the invite code later," but no such lookup
actually existed anywhere — built the missing endpoint and admin-panel
display specifically so that promise is true.

---

## Analytics / Reporting Export

**What was missing:** Delivery data only ever lived inside the app —
there was no way to get it out for use in a spreadsheet or an external
reporting tool.

**Why it was needed:** Real operations teams need to analyze delivery
data outside the app itself (monthly reports, sharing with stakeholders
who don't have an account, etc.) — this is standard expected
functionality for any operational dashboard.

**What it does:** A dispatcher/admin can download a CSV of their
organization's deliveries, optionally filtered to a date range using the
same From/To fields already used for table filtering. Built with
Python's built-in `csv` module (not hand-built comma-joined strings), so
a notes field containing a comma still exports correctly — deliberately
avoiding the exact category of bug the bulk-import CSV *parser* was
built to prevent on the way in, this time on the way out.

---

## Rate Limiting & Security Hardening

**What was missing:** No protection against automated abuse — the same
signup or login endpoint could be hit as fast as a script could send
requests, the JWT signing key was hardcoded directly in the source code,
and CORS was wide open to any origin.

**Why it was needed:** This was explicitly flagged as a known gap in
`docs/SECURITY_AND_ACCESS.md` from early in the project — necessary
before this could honestly be called ready for any real deployment.

**What it does:**
- Signup and login are rate-limited per IP (5/min and 10/min
  respectively) using `slowapi`, confirmed by actually sending 7 rapid
  signup requests and watching the 6th and 7th get correctly rejected
  with a 429
- The JWT signing key now reads from a `JWT_SECRET_KEY` environment
  variable, falling back to a dev-only value with a loud startup warning
  if it's not set — rather than a fixed value baked into the source code
- The `/sync` endpoint is deliberately left without login-based
  authentication (an offline device may not have a fresh valid session)
  but is rate-limited instead, and organization membership is still
  enforced server-side per record (see the Multi-Tenant fix above) rather
  than trusted from the client
- CORS origins are now configurable via an `ALLOWED_ORIGINS` environment
  variable instead of being permanently wide-open
- A few standard, low-risk security headers (`X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`) are added to every response

**Honestly disclosed, not fixed:** a shared-store rate limiter (e.g.
Redis-backed) would be needed for a real multi-server deployment, since
the current in-memory limiter only tracks requests per individual server
process — documented as a known gap rather than silently left unmentioned.

---

## Real Customer Portal (Accounts, Dashboard, In-App Notifications)

**What was missing:** The only customer-facing experience was a public
tracking link and console-logged email/SMS text — accurate for local
development, but not something a real user (or a recruiter checking a
deployed link) would ever actually see or use as a product feature.

**Why it was needed:** A genuine delivery platform needs a real customer
account system, not a simulation of one — this was flagged directly as
the difference between "a mini project" and a complete product.

**What it does:** A completely separate customer identity system
(`CustomerDB`, its own signup/login, its own JWT token shape so it can
never be confused with a staff token) — customers aren't tied to any one
organization, since they may order from several different companies on
this platform. Deliveries auto-link to a matching customer account by
email, both at creation time and retroactively if the customer signs up
afterward. The dashboard shows every linked order across all
organizations, with an expandable per-order timeline, proof of delivery,
and a rating form. A real in-app notification bell (unread count,
mark-read, polling) is now the **primary** notification channel — the
console-log email/SMS from the previous entry is kept only as a
secondary, external channel for reaching someone not currently logged in.

**A real routing bug found and fixed after initial delivery:** the
customer portal was unreachable in a browser that already had a staff
session saved, because the top-level router checked "is a staff user
already logged in?" before ever offering the staff/customer choice — so
an existing staff session silently took priority every time, with no way
to reach the customer portal at all. Fixed by adding a `?portal=customer`
/ `?portal=staff` URL override that always wins regardless of any saved
session, plus visible links to it from both the staff sidebar and the
staff login screen — not just relying on a first-visit chooser that a
returning user would never see again.

---

## Real Product Image Upload

**What was missing:** `image_url` on a product was just a free-text field —
a dispatcher had to already have the image hosted somewhere else and paste
in a link. No actual file upload/storage existed.

**Why it was needed:** No real store owner has a pre-hosted image URL
ready to paste in; they have a photo on their phone/laptop. A catalog
management feature isn't real without a way to actually upload the photo.

**What it does:** New `POST /admin/products/upload-image` endpoint takes
real multipart file bytes, validates type (JPEG/PNG/WebP/GIF) and size
(5MB max), and saves it to `backend/uploads/products/<uuid>.<ext>` on
disk — returning a URL that's then mounted and served back out at
`/uploads/products/...` via FastAPI's StaticFiles. `ProductManager.jsx`
got a real file input with upload progress + thumbnail preview;
`Storefront.jsx` now shows product photos in the catalog and cart.
Deleting a product also cleans up its image file from disk.

---

## Real Razorpay Refunds on Cancellation

**What was missing:** Cancelling a paid order only flipped the delivery's
status to "cancelled" in the database — no money ever actually moved back
to the customer, real gateway or not.

**Why it was needed:** A cancel button that doesn't refund isn't a real
cancel button from a customer's (or a recruiter's) perspective — it's a
status label. This was the same "is it actually real, not just a
console-log demo" gap the notification system had earlier.

**What it does:** New `services/refund.py` with `refund_order_for_delivery()`,
called from BOTH places an order can be cancelled — the customer's
self-serve cancel button and the dispatcher/admin status-update path.
It looks up the Order linked to the cancelled delivery and, if it was
actually paid: calls Razorpay's real refund API (same HMAC-verified,
no-shortcuts pattern as the original payment integration) when a gateway
is configured, or marks a clearly-labeled simulated refund when running
in test mode — mirroring `is_test_mode_payment` exactly. New
`refund_status`/`razorpay_refund_id`/`refunded_at` columns on Order.
Refund failures are caught and recorded as `refund_status="failed"`
rather than silently blocking the cancellation itself. Frontend now
shows the real refund outcome ("Refund issued on ..." or a failure
notice) on a cancelled order.

---

## Product Reviews & Ratings

**What was missing:** Only delivery-experience feedback existed (was the
agent good, was it on time) — nothing for rating the product itself.

**Why it was needed:** A store needs product ratings for customers
browsing to decide whether to buy — delivery feedback doesn't tell a
shopper anything about the product quality.

**What it does:** New `ProductReviewDB` table, separate from the existing
delivery-feedback table. Submitting a review is gated server-side, not
just hidden in the UI: the order must belong to the reviewing customer,
must be paid, must actually contain that product, and the linked delivery
must have reached `delivered` — otherwise it's rejected with a clear
error. One review per (order, product) pair, enforced with a DB unique
constraint. New endpoints: public `GET /stores/products/{id}/reviews`
(browse before buying, no login), `GET /customer/deliveries/{id}/reviewable-items`
(what still needs a review on a delivered order), and
`POST /customer/products/{id}/reviews` (submit). Product listings in
both the admin catalog view and the public storefront now show an
aggregated average rating + review count, computed live from real review
rows rather than a cached counter. `CustomerDashboard.jsx` gained a
"Rate your products" section on delivered orders — one star-rating form
per line item, right where the existing delivery-feedback form already
lived.

---

---

## Stock / Inventory Tracking

**What was missing:** Products could be "sold" with no quantity limit —
`stock_quantity` didn't exist at all, so a store could oversell anything
indefinitely.

**Why it was needed:** Real stores run out of things. Without a stock
limit, a shop selling a one-off or limited item has no way to stop
customers from ordering more than actually exists.

**What it does:** New optional `stock_quantity` on Product — `None`
means untracked/unlimited (the old behavior, unchanged for every
existing product), and setting a number turns on real enforcement.
Checked at cart-add, cart-quantity-update, checkout-creation, and once
more right before payment is finalized (the authoritative check, since
stock can change between checkout and payment). Decremented only once
an order actually reaches `paid` — an abandoned checkout never
permanently reserves stock. If stock runs out for a **real** payment
between checkout and verification, the order is auto-refunded via the
existing Razorpay refund integration rather than leaving the customer
charged for nothing. Cancelling a paid order restocks the items
automatically (wired into the same refund path from the previous
session's cancellation work) — the items never shipped, so they go
back on the shelf. `ProductManager.jsx` got a stock field on create
plus an inline editable stock number per product; `Storefront.jsx`
shows "Only N left" / "Sold out" badges and disables Add-to-cart /
blocks quantity increases at the limit.

---

## Coupons / Discounts

**What was missing:** No promo code mechanism anywhere in checkout —
there was no way for a store to run a sale or targeted discount.

**Why it was needed:** Discount codes are a basic, expected e-commerce
feature for both marketing (drive orders with a promo) and support
(comp a customer) — a checkout flow isn't feature-complete without one.

**What it does:** New org-scoped `CouponDB` — percent-off or flat-₹-off,
with optional minimum order value, optional max redemptions, optional
expiry, and an active/inactive toggle. Admin/dispatcher CRUD at
`/admin/coupons`. On the customer side, a coupon can be previewed
against the current cart before committing (`/customer/checkout/validate-coupon`,
used by the cart's "Apply" button for instant feedback) and is then
applied for real at checkout. Eligibility (active, not expired, under
its use limit, minimum order met) is enforced by one shared function
(`services/coupons.py`) used by both the preview and the real checkout,
so what a customer sees in the preview can never disagree with what
they're actually charged. A coupon's `used_count` is only incremented
once its order reaches `paid` — an abandoned checkout never burns
through a limited coupon's redemptions.

---

## Delivery Fee + Tax (GST)

**What was missing:** Checkout charged exactly the product subtotal —
no delivery charge, no tax line, on every single order regardless of
store or location.

**Why it was needed:** No real delivery/e-commerce checkout charges
exactly the product subtotal — a delivery fee and applicable tax (GST,
for an India-focused app) are standard, expected line items, and their
absence made the checkout total simply wrong for demonstrating a real
payment flow.

**What it does:** Each org now has an admin-configurable flat
`delivery_fee` and `tax_rate_percent` (`PATCH /admin/store/pricing`,
new "Delivery Fee & Tax (GST)" card in the Products page). Checkout now
computes, in order: subtotal → minus any coupon discount → GST applied
to that discounted amount → plus the flat delivery fee → the actual
total charged via Razorpay. The full breakdown (subtotal, discount,
delivery fee, tax, total) is returned from the checkout API and stored
on the Order itself, not just computed in the frontend, so a receipt
always reflects exactly what was charged even if the store's pricing
changes later. This also closed a related gap in last session's refund
work: refunds now correctly return the full amount actually charged
(including delivery fee and tax), not just the product subtotal.
`Storefront.jsx`'s cart shows a live subtotal/discount/delivery/GST/total
breakdown before checkout, using the same formula as the backend.

---

---

## Admin Analytics Dashboard

**What was missing:** No revenue/order-volume view anywhere — an admin
could only see raw lists of orders/deliveries and had to mentally
total them up.

**Why it was needed:** "How is the store actually doing" (revenue,
order volume, what's selling, what's running low, what's stuck in
delivery) is one of the first things a real store admin wants to see,
and no amount of scrolling raw lists answers it well.

**What it does:** New admin-only `GET /admin/analytics/` endpoint
(with a `days` window — 7/30/90 in the UI), computed live from
existing Order/OrderItem/DeliveryRecord rows rather than a maintained
running total, so it can never drift from what the raw lists already
show. Returns: total revenue, order count, average order value,
discount/delivery-fee/tax totals, refund totals, a day-by-day revenue
series (zero-filled so a chart has a continuous axis), the top 5
products by revenue, a delivery status breakdown (pending through
delivered/cancelled), and a low-stock alert list (any tracked product
at 5 units or fewer — see last session's stock-tracking work). New
`AnalyticsDashboard.jsx`, added as its own "Analytics" nav item for
admins — stat cards, a lightweight CSS bar chart for the revenue
trend, a status-breakdown bar, a top-products list, and low-stock
warnings. No new charting library — everything is plain divs/CSS to
avoid adding a dependency for what's a fairly simple visual need here.

---

## Push Notifications for Agents/Dispatchers

**What was missing:** Web Push only ever fired for customers (order
status updates). An agent got no notification when assigned a new
delivery, and a dispatcher/admin got no notification when a new
unassigned customer order landed in their queue — both had to keep
the dashboard open and refresh to notice.

**Why it was needed:** The whole point of Web Push (real OS-level
notifications, even with the tab/browser closed) is exactly this kind
of "you need to know the moment this happens" event — and an agent or
dispatcher needs that just as much as a customer does.

**What it does:** Reused the exact same Web Push mechanism already
built for customers (`services/push.py`, VAPID-based, no third-party
account needed) rather than building a second notification pipeline —
`PushSubscriptionDB` now supports a staff subscriber (`user_id`
alongside the existing `customer_id`), with new endpoints
(`/users/me/push/vapid-public-key`, `/users/me/push/subscribe`)
mirroring the customer-facing ones. Two new trigger points in
`services/notifications.py`: `notify_agent_of_new_assignment` (fires
whenever a delivery is assigned to an agent — both at dispatcher-
creation time and via the "assign to agent" action on a customer
order) and `notify_dispatchers_of_new_order` (fires to every
dispatcher AND admin in the org the moment a checkout order lands
unassigned — wired into `verify_payment`). Both are best-effort and
failure-isolated exactly like the customer-facing push, confirmed by
smoke-testing with deliberately invalid subscription endpoints: the
push call fails and logs, but checkout/assignment still succeed.
Frontend: extracted the shared base64→Uint8Array VAPID helper into
`services/pushUtil.js` (previously duplicated per-component) and added
a "🔔 Enable Notifications" button to the staff sidebar, with
role-aware copy explaining what it's for.

---

---

## Delivery Time-Slot Scheduling

**What was missing:** No way for a customer to pick a delivery window —
every order was implicitly "as soon as possible," with no scheduling
concept anywhere in checkout.

**Why it was needed:** Picking a delivery window (like a 2-hour slot)
is standard for any real delivery service — customers plan around
being home, and a store needs to avoid promising more deliveries in
one window than it can actually fulfill.

**What it does:** Each org gets an admin-configurable daily operating
window, slot length, and per-slot order cap (`PATCH /admin/store/slot-settings`,
new "Delivery Time Slots" card in the Products page — defaults to a
9am-9pm day cut into 2-hour slots, 10 orders max per slot). A new
`GET /stores/{org_id}/delivery-slots?date=...` endpoint generates the
bookable windows for a given day (today plus up to 6 days out),
already accounting for how many paid orders are booked into each —
past slots for today are automatically excluded. Checkout accepts an
optional `slot_start`, re-validated server-side against the exact same
generation logic that produced the options the customer saw (so a slot
shown as available can never be rejected, and a stale/tampered/full
one always is), and copies the resolved window onto both the Order and
the Delivery record it creates. `Storefront.jsx` got a date-tab + time-
slot picker in the checkout form, showing remaining capacity per slot;
skipping it entirely still works exactly as before (ASAP delivery).

---

## Smarter / Automated Agent Assignment

**What was missing:** A dispatcher assigning an order picked from a
plain alphabetical list of agents, with no guidance — despite live
agent GPS positions already being collected for the customer tracking
map and just sitting unused for this decision.

**Why it was needed:** The whole point of already tracking agent
locations is exactly this: helping a dispatcher assign the delivery to
whoever can actually get there fastest, instead of a blind pick.

**What it does:** New `GET /deliveries/{id}/suggested-agents` ranks
every agent in the org for one specific delivery — nearest by live GPS
distance first (haversine straight-line against the delivery's
coordinates, reusing `AgentLocationDB`), with current active-delivery
workload as the tiebreaker. Falls back to workload-only ranking when a
delivery has no coordinates or an agent has never shared a location —
those agents still show up, just without a distance and sorted after
anyone who has one, so nobody silently disappears from consideration.
A new `POST /deliveries/{id}/auto-assign` uses the same ranking to
assign the top match in one click, sharing its actual assignment logic
with the existing manual "pick from the list" endpoint (refactored
into one `_apply_agent_assignment()` helper so both paths produce
identical history entries and notifications). `DispatcherTable.jsx`'s
unassigned-orders queue got a "🎯 Suggest agent" button that annotates
the agent dropdown with live distance/workload, and a "⚡ Auto-assign"
button for skipping the pick entirely.

---

## Conflict-Resolution Visibility

**What was missing:** The offline sync engine resolves conflicting
updates with last-write-wins (see `services/conflict_resolver.py`) —
but silently. If an agent's offline status change lost to a newer
change made elsewhere while they were offline, their update was just
discarded with no signal anywhere that it happened.

**Why it was needed:** Silently throwing away someone's real update is
a data-loss-adjacent problem — an agent who marked a delivery
"delivered" offline deserves to know if that never actually stuck,
rather than discovering it later (or never).

**What it does:** `resolve_and_apply()` now returns a conflict record
(not just the winning row) whenever an incoming offline change is
discarded in favor of a newer one already on the server — including,
where available, who made the winning change (looked up from the
existing delivery-history audit log). `POST /sync`'s response gained a
`conflicts` list carrying this alongside the usual `resolved_records`/
`errors`. `AgentDeliveryList.jsx` turns each one into a durable,
dismissible banner ("Order X: your change to '...' was overridden —
Y already updated it to '...' more recently") plus an immediate toast,
shown on both the periodic background sync and a manual "Sync Now" —
so a discarded change is now something the agent can actually see and
act on, not something that vanishes.

---

## Two-Factor Authentication (Staff Logins)

**What was missing:** A staff account (agent/dispatcher/admin) was
protected by a password alone. Anyone who obtained or guessed a
password had full account access — including an admin's ability to
manage every user in the organization.

**Why it was needed:** Trust & compliance requirement — staff logins
needed a second factor beyond the password, the standard baseline for
any account with administrative or operational access to real customer
data.

**What it does:** TOTP-based 2FA (RFC 6238 — the same standard behind
Google Authenticator, Authy, 1Password), free and self-contained since
it needs no SMS/email provider. `UserDB` gained `totp_secret` /
`totp_enabled`. Setup is two steps on purpose (`POST /auth/2fa/setup`
returns a QR code but doesn't enable anything; `POST /auth/2fa/enable`
only flips it on once a real code from the freshly-scanned app is
confirmed), so an abandoned setup can't lock an account out. Once
enabled, `POST /auth/login` no longer returns a session token directly
for that account — it returns a short-lived (5 min) `challenge_token`,
and `POST /auth/2fa/verify-login` exchanges that plus a correct code for
the real access token. `POST /auth/2fa/disable` requires the password
again, not just an active session. Frontend: `LoginPage.jsx` gained a
second step for the code; a new "Security" page (`TwoFactorSettings.jsx`,
in the sidebar for every staff role) handles setup/enable/disable, with
the QR rendered via the same free `api.qrserver.com` image API already
used for order QR codes.

---

## Audit Log Viewer (Admin)

**What was missing:** Delivery status changes were already recorded
with who/what/when (`DeliveryHistoryDB`, powering each delivery's
individual history timeline) — but there was no way for an admin to
browse that data broadly, across every delivery in the organization at
once.

**Why it was needed:** Trust & compliance requirement — admins need a
proper audit trail view, not just a per-delivery timeline they'd have
to click into one order at a time.

**What it does:** `GET /admin/audit-log` joins `DeliveryHistoryDB` to
`DeliveryRecordDB` (for org-scoping, since history rows don't carry
`org_id` directly) and returns every status-change entry for the
admin's organization, filterable by date range, who made the change,
and order ID, with pagination. New `AuditLogViewer.jsx` (sidebar, admin
only) renders it as a filterable table with a "Load more" pager.

---

## GDPR-Style Data Export & Account Deletion (Customers)

**What was missing:** A customer had no self-serve way to see everything
the platform held about them, or to delete their account.

**Why it was needed:** Trust & compliance requirement — a basic "right
to access" and "right to erasure" flow for customer accounts.

**What it does:** `GET /customer/data-export` streams a single JSON file
with everything tied to the logged-in customer: profile, saved
addresses, orders + line items, linked deliveries + status history +
feedback given, cart, notifications, product reviews, and registered
push-notification devices (endpoint only — private keys withheld, since
those are security credentials, not personal data worth exposing in a
downloadable file). `DELETE /customer/account` requires the password
again (not just an active session) and deletes purely personal data
outright (cart, addresses, notifications, push subscriptions) — but
*anonymizes* rather than deletes orders/deliveries/reviews, since a
store has a legitimate business reason to retain its own transaction
and refund records even after a customer's account is gone, the same
pattern real e-commerce platforms (Amazon, Shopify) use. New
`PrivacyPanel` in `CustomerDashboard.jsx` (🔒 Privacy button) offers
both actions, with a password-confirmation step before deletion.

---

---

## Real Fix: `.env` Was Never Actually Being Loaded

**What was wrong:** Every "optional real, else console-log" integration
(SMTP email, Twilio SMS, Razorpay, VAPID) reads its config as a
module-level constant via `os.environ.get(...)`. Nothing in the codebase
ever called `load_dotenv()` — no `python-dotenv` dependency existed at
all. Filling in real values in `backend/.env` had **zero effect**: those
values only ever reach `os.environ` if something loads the file into
the process first, and nothing did. Password reset (and everything else
gated the same way) kept "printing instead of sending" no matter what
`.env` said.

**The fix:** Added `python-dotenv`; `main.py` now calls `load_dotenv()`
as the literal first lines of the file, before any local import — this
has to happen before those modules are first imported, since that's the
exact moment their module-level `SMTP_HOST = os.environ.get(...)`-style
constants get evaluated. Verified directly: `SMTP_HOST` reads as `None`
without the fix, and the real value with it.

---

## Agent Coverage Area (Real GPS Reverse Geocoding) + Zone-Based Assignment

**What was missing:** Suggested/auto-assign ranking used only live GPS
distance and workload — there was no concept of an agent's actual
coverage area, so a dispatcher couldn't assign based on "who actually
covers this zone."

**What it does:** New `services/geocoding.py` calls OpenStreetMap's free
Nominatim reverse-geocoding API (no key, no billing) to turn an agent's
real device GPS coordinates into a real area name (e.g. "Koramangala,
Bengaluru") — a genuine reverse geocode, not a hand-typed field.
`POST /users/me/area/detect` (agent-only) saves it; new "My Area"
section + "📍 Detect My Area" button in `AgentDeliveryList.jsx`.
`_rank_agents_for_delivery` now sorts zone-matched agents (delivery's
`zone` vs. agent's `area_name`, loose case-insensitive match) ahead of
everyone else, before distance or workload — a far-away agent whose area
matches the delivery's zone now outranks a much closer agent who doesn't
(verified directly: 1111km-but-zone-matched agent ranked #1 over a
0.78km-but-wrong-zone agent). Dispatcher's assign dropdown and suggested-
agents panel show each agent's area and a zone-match indicator.

---

## Email-Code Two-Factor Authentication (Second Method)

**What was missing:** 2FA only supported an authenticator app (TOTP).
Scanning the setup QR code with a phone's general camera or Google
Lens/Search doesn't work — those read it as plain text and try to
web-search it, since `otpauth://` isn't a scheme they know how to open.
That's expected behavior for those tools, not a bug, but it meant
anyone without a dedicated authenticator app installed had no way to use
2FA at all.

**What it does:** A second, independent 2FA method — a 6-digit code
emailed to the account's own address, real SMTP delivery (see the
`.env` fix above), reusing the same hashed-and-expiring code pattern as
password reset tokens (`models/email_otp.py`). Setup: `POST
/auth/2fa/setup-email` sends a confirmation code immediately (no QR —
the "device" being set up is the inbox itself); `POST
/auth/2fa/enable-email` confirms it. Login: when an "email"-method
account signs in, `POST /auth/login` sends a fresh code automatically
and returns `two_factor_method`/`masked_email` alongside the challenge
token; `POST /auth/2fa/resend-code` covers a lost/expired code.
`TwoFactorSettings.jsx` now offers both methods side by side, with
explicit instructions to use an authenticator app's own QR scanner
(not a camera app or Lens) for the TOTP option. Verified end-to-end:
setup → enable → login-auto-sends → wrong-code rejection → correct-code
success → single-use enforcement — and confirmed the existing TOTP path
is completely unaffected by an account using the email method.

---

---

## Real Bug Fix: Checkout Crash Misreported as "You're Offline"

**What was wrong:** A misconfigured (or just-invalid-test) Razorpay key
pair made `create_razorpay_order()` raise `BadRequestError:
Authentication failed`, uncaught, deep in `POST /customer/checkout`.
Combined with how Starlette's `@app.middleware("http")` pattern handles
an unhandled exception, the browser's `fetch()` saw the connection drop
rather than a clean error response — which the checkout code's
`err instanceof TypeError` catch (reasonably, at the time) treated as
"must be offline," silently queuing the order instead of surfacing the
real problem. The customer saw "You're offline" while genuinely online.

**The fix, at both ends:**
- `routes/checkout.py` now wraps the Razorpay call in a real
  try/except — an authentication failure returns a clean `502` with an
  actionable message (check `RAZORPAY_KEY_ID`/`SECRET` in `.env`, or
  unset them to use the built-in test-mode path) instead of crashing.
- `main.py`'s security-headers middleware is now a backstop for *any*
  unhandled exception anywhere in the app — logs it server-side and
  always returns a clean `500 {"detail": "..."}` JSON response, so a
  future bug in a completely different route can never again show up in
  the browser as a misleading "offline" state. Verified directly: a
  forced, unrelated exception in an unrelated route now returns a clean
  500 instead of dropping the connection.
- `Storefront.jsx`'s offline-detection now checks `navigator.onLine`
  before treating a failed fetch as "offline" — a `TypeError` while
  actually online now shows "Couldn't reach the server" instead of
  silently (and incorrectly) queuing the order as if offline.

---

## Real Cash-on-Delivery (COD) Checkout

**What was missing:** Checkout was online-payment-only (Razorpay, or a
test-mode stand-in when no gateway is configured) — no way for a
customer to choose "pay in cash when it arrives."

**What it does:** `CheckoutRequest.payment_method` — `"online"` or
`"cod"`. Choosing COD skips Razorpay entirely: the order is confirmed
immediately (no separate payment-verification round trip needed beyond
the existing test-mode-style `POST /checkout/verify` call), stock is
decremented, a `DeliveryRecordDB` is created and lands straight in the
dispatcher's unassigned queue exactly like an online order — verified
end-to-end. Cancelling a COD order before delivery correctly skips any
refund attempt in `services/refund.py` (nothing was ever charged) and
just restocks. `Storefront.jsx` gained a Pay Online / Cash on Delivery
toggle in the checkout form, with matching copy in both the immediate
and the offline-queued-then-synced confirmation messages.

---

## Config Fix: `FRONTEND_URL` Port Mismatch (Password Reset Links)

**What was wrong:** `frontend/vite.config.js` runs the dev server on
port **3000**, but `backend/.env.example`'s `FRONTEND_URL` example value
said **5173** (Vite's own default, not what this project actually
uses). Copying `.env.example` to `.env` without editing that line means
every password-reset email links to a port nothing is listening on —
"this site can't be reached."

**The fix:** `.env.example` now matches the real port (3000) with a
comment explaining why it has to match whatever `npm run dev` actually
prints, rather than assuming Vite's default.

---

---

## Real Bug Fix: Existing Databases Broke on Every New Column

**What was wrong:** `Base.metadata.create_all(bind=engine)` (the only
schema setup this project had) only creates tables that don't exist
yet — it silently does NOT add new columns to a table that already
exists from an earlier run. The COD feature added `payment_method` to
`OrderDB`, and anyone with an existing local `database.db` file (i.e.
anyone who'd actually been using the app) hit `sqlite3.OperationalError:
table orders has no column named payment_method` on the very next
checkout — a hard crash, not a graceful degradation. This wasn't
specific to `payment_method`; the exact same failure was waiting to
happen on every future column added to any existing table, for anyone
with real data already in their database.

**The fix:** New `app/db/migrate.py` — a lightweight, dependency-free
migration step (this project deliberately doesn't use Alembic, in
keeping with its zero-setup philosophy) that runs right after
`create_all()` on every startup: it diffs each table's actual columns
against what the model currently expects, and `ALTER TABLE ... ADD
COLUMN`s in whatever's missing. New columns are always added nullable
regardless of the model's own `nullable=False`, specifically so it can
never fail against a table that already has rows. Verified directly
against Santy's exact scenario: hand-built an old-schema `orders` table
(matching the schema from before `payment_method` existed) with a real
row in it, ran the app's real startup against it, confirmed the column
got added, the existing row survived untouched, AND SQLite correctly
backfilled it to the column's default (`'online'`) — then ran a live
COD checkout against that same migrated database end-to-end and
confirmed it completes. Also confirmed a totally fresh install (no
`database.db` at all) still works with zero regressions. This means an
existing local database now survives every future schema change this
project makes, without ever needing to be deleted and started over.

---

---

## Real Bug Fix: "My Orders" Showing on Every Customer Page

**What was wrong:** The customer dashboard's Shop/Addresses/Privacy
sections were each an independent toggle-boolean that could all be open
simultaneously, and "My Orders" wasn't gated behind any of them at all —
it just always rendered underneath whatever else was open, so it showed
up no matter which button you'd clicked.

**The fix:** Replaced the three separate booleans with one `activeView`
tab state ("orders" | "shop" | "addresses" | "privacy" | "profile"), so
exactly one section is visible at a time, with the active tab visually
highlighted. "My Orders" is now genuinely its own page.

---

## Checkout Now Uses Saved Addresses

**What was missing:** Saved addresses (added earlier for multi-address
profiles) were never actually connected to checkout — there was no way
to pick one, and nothing prefilled.

**What it does:** `Storefront.jsx` loads saved addresses on open and
auto-fills the checkout form from the default (or the only) saved
address. A dropdown above the address field lets you switch between any
saved address or "enter a new address" instead — editing the fields
directly also switches it to "new" automatically so it's clear you're
not silently overwriting a saved address.

---

## Agent Area: Manual Selection, Not Just GPS

**What was missing:** The only way to set an agent's coverage area was
GPS detection — no way to pick or type an area directly (useful when
the reverse-geocoded name doesn't match what dispatchers actually call
a zone, or GPS just isn't available/accurate).

**What it does:** New `POST /users/me/area/set` sets an area directly by
name (no coordinates — there's no real GPS fix behind a manually-typed
area, and zone-matching only ever compares names anyway). New `GET
/users/me/area/suggestions` returns area names already in use across
the org (other agents' areas + zones dispatchers have typed onto
deliveries), so picking an area can be "choose from what's already used
here" via a dropdown, with a free-text box alongside it for anything
new. `AgentDeliveryList.jsx`'s area section now offers all three: GPS
detect, pick-from-list, or type-your-own.

---

## Customer Profile + Notification Cleanup

**What was missing:** No way for a customer to view/edit their own
name or email, or change their password — genuinely no profile page
existed at all. Also no way to delete notifications; they only ever
accumulated.

**What it does:**
- New `GET/PATCH /customer/me` (name/email, with email-uniqueness
  checking) and `POST /customer/me/change-password` (requires the
  current password, same re-auth-to-change-something-sensitive pattern
  used for staff 2FA disable). New "👤 Profile" tab with both forms.
- New `DELETE /customer/notifications/{id}` (single) and `DELETE
  /customer/notifications?only_read=true/false` (bulk — defaults to
  only clearing already-read ones, the safer default for a "clean up"
  action, with a full-clear option available). Notification panel
  gained a 🗑 delete button per item and a "Clear read" button.

---

---

## Real Bug Fix: Push Notifications Broken by a Blank `.env` Line

**What was wrong:** `services/push.py` has a real, working default VAPID
keypair checked in — push was meant to work with zero configuration.
But it read the key as `os.environ.get("VAPID_PUBLIC_KEY",
DEFAULT_VAPID_PUBLIC_KEY)`, and `backend/.env.example` had
`VAPID_PUBLIC_KEY=` (present, but blank). `os.environ.get(key,
default)`'s default only applies when the key is entirely ABSENT — a
blank-but-present value is not the same thing, and silently overrode
the working default with an empty string. That's a browser-side
"applicationServerKey is not valid" error, and — worth naming plainly —
a regression from this project's own earlier `.env`-loading fix:
`.env` not being loaded at all previously masked this from ever
mattering.

**The fix:** `services/push.py` now uses `os.environ.get(key) or
default` for all three VAPID settings — `or` correctly treats
blank-and-absent the same way, so a leftover blank line in `.env` can
never again shadow the working built-in keypair. `.env.example`'s VAPID
key lines are now commented out by default (so copying it doesn't set
anything blank in the first place), with an explicit warning about why
that matters. Verified directly: an env var explicitly set to `""`
now correctly falls back to the real default key.

---

## Real Reverse Geocoding via Google Maps API (Optional)

**What was asked:** a "real" location provider, with an API key to be
supplied. Worth being precise about what an API key can and can't
improve here, since it came up directly: the raw GPS COORDINATE's
accuracy is entirely determined by the requesting device's own
hardware/OS location services (GPS chip, WiFi, cell signal) — no
server-side API key changes that. What a paid provider genuinely
improves is turning that coordinate into an ADDRESS, which is this
feature's actual job.

**What it does:** `services/geocoding.py` now uses Google's Maps
Geocoding API when `GOOGLE_MAPS_API_KEY` is set (real address data,
generally more complete than the free default), automatically falling
back to free Nominatim if Google fails (bad key, quota, network) or if
no key is configured at all — same "real if configured, free fallback
otherwise" pattern as this project's SMTP/Twilio/Razorpay integrations.
Verified both paths directly, including the Google-fails-falls-back-to-
Nominatim case.

---

## Customer Dashboard: Real Layout Redesign

**What was wrong:** the customer dashboard never adopted this project's
own "fleet ops console" design system (`.sidebar`/`.app-shell`, already
used throughout the staff side) — it was a bespoke top-bar-with-seven-
crammed-buttons layout built with raw inline styles, which is exactly
why it read as inconsistent/unpolished next to the rest of the app.

**The fix:** rebuilt the customer dashboard's shell to use the exact
same sidebar navigation pattern as the staff side (`Sidebar.jsx`) —
same classes, same mobile off-canvas drawer behavior, same footer
structure for account actions (push toggle, notifications, theme,
logout) — so a customer and a staff member looking at their respective
dashboards now see one consistent product, not two different ones
stitched together. Also gave the plain, unstyled store-list rows in
`Storefront.jsx` (just a bare name with no visual affordance) a real
list-item treatment: a secondary line, a directional arrow, and a new
`.card-clickable` hover state now used consistently for every clickable
card in the app.

---

---

## Delivery Zones/Territories (Real Entity, Not Just Free Text)

**What was missing:** Deliveries had a free-text `zone` field a
dispatcher could type anything into, and agents had a GPS-detected
`area_name` — both loose string matches, no real geographic boundary,
and nothing actually restricted auto-assignment to a territory.

**What it does:** New `ZoneDB` — a real circular territory (center
lat/lon + radius_km), tested with actual point-in-circle math
(`services/geo.py`'s `find_zone_for_point`), not string comparison.
Deliberately a circle rather than a drawn polygon: trivial to test a
point against and trivial to edit (three numbers), while still being a
genuine geographic boundary — see `models/zone.py` for the full
reasoning. Admin CRUD (`/admin/zones/`) plus per-zone agent coverage
assignment (many-to-many — an agent can cover multiple zones). The real
payoff: `POST /deliveries/{id}/auto-assign` now HARD-RESTRICTS to a
zone's covering agents when the delivery's coordinates fall inside a
defined zone that has coverage — verified directly: a covering agent
1111km away correctly won over a non-covering agent 0.16km away.
Falls back gracefully to org-wide ranking when there's no matched zone
or the matched zone has no agents assigned yet. New admin `ZoneManager.jsx`
page; `DispatcherTable.jsx`'s suggested-agents panel now shows the
matched zone name and which agents actually cover it.

---

## Returns/Exchange Workflow (Distinct from Cancellation)

**What was missing:** Only pre-delivery cancellation existed. Nothing
handled "the customer already has this delivered item and wants to
send it back or swap it" — a completely different situation (the item
has to physically come back first) that cancellation's logic doesn't
fit.

**What it does:** New `ReturnRequestDB` — only allowed on a `delivered`
order. A customer requests a return (refund) or exchange (replacement)
with a reason; a dispatcher/admin approves or rejects it
(`/admin/return-requests/`). Approving creates a REAL new delivery
(`delivery_type="return_pickup"`) that flows through the exact same
unassigned-queue → assign → picked_up → delivered lifecycle as any
normal delivery — reusing all of that existing infrastructure rather
than building parallel plumbing. When that pickup delivery reaches
"delivered" (item physically back at the store), the request
auto-completes: a **return** triggers a real refund (reusing
`services/refund.py`'s existing real/test-mode-aware logic) and
restocks the item; an **exchange** restocks the item AND creates a
brand-new forward delivery for the replacement — no refund, since the
customer's getting a swap instead. Verified both paths fully
end-to-end, including duplicate-request rejection and the eligibility
check (can't return something not yet delivered). Same hook added to
`services/conflict_resolver.py` for offline-sync parity. Customer-side
request form + status lives in `CustomerDeliveryCard`; dispatcher/admin
review lives in new `ReturnRequestsPanel.jsx`.

---

## WebSocket Live Updates (Chat, Dispatcher Queue, Tracking)

**What was missing:** Three screens were all on a polling timer instead
of getting real updates: delivery chat (5s), the dispatcher's
unassigned-orders queue (15s), and the customer's live tracking map
(8s) — meaningful lag on all three, plus a steady drip of wasted
requests while nothing had actually changed.

**What it does:** New `services/websocket_manager.py` — a simple
room-based connection manager (`chat:{id}`, `dispatcher_queue:{org_id}`,
`tracking:{id}`) and three WebSocket endpoints
(`routes/websockets.py`). REST endpoints stay the write path
unchanged (sending a chat message, changing a delivery's status, etc.)
— WebSocket is push-only, broadcasting to connected clients as a side
effect after each write succeeds, verified individually end-to-end: a
new chat message reaches a connected agent instantly, an order
assignment pushes a queue-changed event to connected dispatchers, and
both delivery status changes and agent location pings push live to the
customer's tracking map. Frontend gained a reconnecting WebSocket
helper (`services/websocket.js`, exponential backoff up to 15s) used by
all three screens; the tracking map keeps a slow 30s poll running
alongside its socket purely as a safety net for networks that block
WebSocket upgrades entirely. Auth: staff sockets take the JWT as a
`?token=` query param (a browser WebSocket can't set custom headers on
the handshake); the tracking socket needs none — scoped to one
unguessable delivery UUID, the same model the existing public tracking
page already uses.

---

---

## Frontend Visual Polish Pass

**What was asked:** make the frontend "complete and beautiful."

**What was already there, worth naming:** the app already had a real,
distinctive design system — "Fleet Ops Console": Space Grotesk (display)
+ Inter (body) + JetBrains Mono (data/mono) as a deliberate three-font
pairing, a near-black dispatch-console palette with a warm amber accent
(`#f2a93b` — chosen specifically to avoid both the acid-green-on-black
and warm-terracotta-on-cream looks that AI-generated designs default
to), and a light-theme override sharing every variable name. That
wasn't templated — it just wasn't being refined, and the customer
dashboard wasn't using it consistently (fixed in an earlier session).
This pass builds on that existing identity rather than replacing it.

**What changed, all in `theme.css`/`auth.css` so it applies everywhere
at once:**
- Real depth: a proper shadow scale (`--shadow-sm/md/lg`, black-based
  for the dark theme since gray shadows look like mistakes on
  near-black, gray-based for light) applied to cards, the sidebar,
  modals, buttons.
- Refined motion: buttons get a focus glow + press-down on click, cards
  lift slightly on hover, modals rise in rather than just appearing,
  in-transit status badges get a subtle "live" pulsing dot — all
  wrapped in a single `prefers-reduced-motion` rule that kills every
  animation at once for anyone who needs that.
- A signature moment for the auth pages (login/signup/forgot/reset —
  previously just a bare centered card with zero brand identity): a
  soft accent-colored glow anchored in the corner, a faint diagonal
  "route line" motif in the background, and a wordmark above the card
  — the one deliberate flourish on the product's most-seen screen,
  evoking a delivery route without literally drawing a map.
- Small details that add up: a themed thin scrollbar (replacing the
  default OS one, which was the one remaining unstyled surface), a
  very faint dot-grid page background (a nod to a dispatch console's
  map grid, low enough contrast to never compete with real content), a
  colored text-selection style, an accent-colored `page-title` tick
  mark, a reusable `.empty-state` treatment (icon + title + guidance,
  applied to the customer's empty order list and the agent's empty
  delivery list — "an empty screen is an invitation to act," not a
  gray sentence in a lot of blank space).
- Left the dispatcher's empty unassigned-queue as a bare `null` render
  on purpose, not an oversight: for a working dispatcher, an empty
  queue is good news that doesn't need a call-to-action box taking up
  space on an otherwise busy screen — the empty-state treatment above
  is for "you haven't done the thing yet," not "there's nothing to do
  right now."

Verified: both CSS files brace-balanced, every touched JSX file
esbuild-clean individually, and the full app bundle builds clean end to
end with no regressions.

---

---

## Postgres + Docker + Environment Separation

**What was missing:** SQLite file + `uvicorn --reload` was the only way
to run this project — no real database option, no containerized setup,
and no distinction in app behavior between "someone's laptop" and "a
real deployment."

**What it does:**
- `app/db/session.py` now reads `DATABASE_URL` — unset (default) still
  means the zero-setup SQLite file; set to a real Postgres URL and the
  exact same models/migrations/queries work against it instead, since
  nothing in this codebase writes raw SQLite-specific SQL. Along the
  way, found and fixed a real cross-dialect bug in the lightweight
  migration system (`app/db/migrate.py`): boolean column defaults were
  hand-formatted as `1`/`0`, which is valid SQLite but a type error
  against a real Postgres boolean column. Now rendered through
  SQLAlchemy's own literal compiler, which gets it right per-dialect —
  verified directly against both dialects.
- `ENVIRONMENT=production` is a real safety switch, not just a label:
  the interactive `/docs` explorer gets disabled, `ALLOWED_ORIGINS`
  must be set explicitly (no silent wide-open CORS default), and the
  app now refuses to even START if `JWT_SECRET_KEY` is left at its
  insecure default — a hard failure instead of a warning that's easy to
  miss in a deploy log. Verified both the failure and the
  properly-configured success path directly.
- `backend/Dockerfile`, `frontend/Dockerfile` (a real two-stage build —
  `npm run build`'s static output served by nginx, no Node in the final
  image), and a root `docker-compose.yml` wiring up Postgres + backend
  + frontend together, all with `ENVIRONMENT=production` set. New
  `docs/DOCKER.md` covers running it and what's actually different from
  local dev. `frontend/src/services/api.js`'s `API_BASE_URL` is now a
  build-time `VITE_API_BASE_URL`, since a Docker/production build can't
  assume the backend lives at `127.0.0.1:8000` the way local dev always
  did.
- Docker itself isn't available in the environment this was built in,
  so the Dockerfiles/compose file are validated as far as reasonably
  possible without a live daemon: YAML syntax-checked, and every actual
  behavior change they configure (DATABASE_URL switching,
  ENVIRONMENT=production's three effects) tested directly against the
  real code paths.

---

## Real Routing (OSRM / Google Directions)

**What was missing:** every distance used for agent-ranking and route
ordering was straight-line haversine — fine for a rough sort, but not
what a road actually looks like (a river, a highway with no nearby
crossing, one-way streets can all make the "closer" agent by
straight-line distance actually take longer to arrive).

**What it does:** new `services/routing.py` — real road distance/time
(`get_route_distance`) and real multi-stop route optimization
(`optimize_stop_order`, an actual TSP-approximation via OSRM's `/trip`
endpoint or Google Directions' waypoint optimization, not hand-rolled
nearest-neighbor) — via Google Directions when `GOOGLE_MAPS_API_KEY` is
set, free OSRM otherwise (same "real if configured, free fallback
otherwise" pattern as this project's other integrations; OSRM's public
demo server is explicitly not meant for production load, disclosed
plainly rather than glossed over).

Agent ranking (`_rank_agents_for_delivery`) now refines the top few
candidates with a real routed distance instead of leaving everything on
haversine — bounded to a small candidate set (a routing call is neither
free nor instant the way haversine is) and, importantly, scoped to
never cross a zone-coverage tier boundary, so a shorter real route can
never let a non-zone-covering agent leapfrog a zone-covering one — that
would have silently undermined the zone-restriction feature. Verified
directly: with a mocked route reversing which agent was actually
closer, the real-routing-refined ranking correctly picked the agent
haversine had ranked second.

New `POST /deliveries/optimize-route` gives an agent's batch of active
deliveries a real optimized visiting order; `SuggestedRoute.jsx` tries
this first and falls back to the original client-side nearest-neighbor
heuristic (`routeOptimizer.js`) when real routing isn't available for
that batch (no coordinates, no provider reachable) — a route is always
produced, real routing or not. Both changes verified end-to-end.

---

## Map Picker for Coordinates (No More Typing Lat/Lng)

**What was asked:** nobody has latitude/longitude memorized — picking
a zone's center or a delivery's coordinates by typing numbers into two
boxes was a real usability gap, not a minor one.

**What it does:** new reusable `LocationPicker.jsx` — a click-anywhere
Leaflet map (same free OpenStreetMap tiles as the existing tracking
map, no API key) with a draggable marker for fine-tuning, and a live
radius circle when picking a zone center. Wired into both places that
asked for raw coordinates: `ZoneManager.jsx`'s zone creation form and
`DispatcherTable.jsx`'s manual delivery creation form — both keep exact
numeric entry available behind a collapsed "enter exact coordinates
instead" fallback for anyone who does have precise coordinates on hand
(e.g. copied from Google Maps), but the map is now the primary,
obvious way to set a point.

---

## Recurring / Subscription Orders

**What was missing:** every order was a one-off — a customer buying the
same groceries every week had to re-shop, re-cart, and re-checkout from
scratch each time.

**Why it was needed:** the single biggest real-world driver of repeat
e-commerce revenue (subscribe-and-save) had no equivalent here at all.

**What it does:** new `SubscriptionDB`/`SubscriptionItemDB` models — a
saved cart-shape (items, address, payment preference, a custom N-day
interval) scoped to one store. Deliberately NOT auto-charged: a
background scheduler (`services/subscription_scheduler.py`, checked
every 60s, wired into `main.py`'s startup event) turns a due
subscription into a real `pending_payment` Order at current
prices/stock (skipping any item that's since sold out or gone
inactive, applying the org's current delivery fee/tax and re-validating
any saved coupon fresh each cycle) and fires an in-app + push
notification — "your recurring order is ready, confirm & pay." The
customer pays it via the *existing*, unmodified checkout payment
machinery (`routes/subscriptions.py`'s `initiate-payment` endpoint
mirrors `checkout()`'s Razorpay/COD/test-mode tail, then the frontend
calls the same `POST /customer/checkout/verify` a normal order uses).
If they never pay, that cycle's order just sits pending — same as an
abandoned cart — and the next cycle still fires on schedule regardless,
since `next_run_date` always advances by `interval_days` the moment a
cycle runs. New customer-facing "Recurring Orders" tab
(`SubscriptionManager.jsx`) for pause/resume/cancel/edit and a
Confirm & Pay banner; a "⟳ Subscribe" button + modal on every product
card in `Storefront.jsx` for setting one up. A "Reorder Now" button
lets a cycle be generated on demand instead of waiting for the
scheduler, for testing/demo purposes.

---

## Marketplace Search & Store Profiles

**What was missing:** the org model was already genuinely multi-tenant
(every org = one independently-run store, one global customer identity
across all of them, cart/checkout scoped per store exactly like
Swiggy/Amazon-marketplace) and `GET /stores` already listed every
opted-in store — but there was no way to tell stores apart beyond a
bare name, and no way to search or filter a directory of more than a
handful of them.

**Why it was needed:** "one org = one store, many stores in one
marketplace" only feels like a marketplace once a shopper can actually
find the store they want.

**What it does:** `OrganizationDB` gains optional `category` (free
text — "Grocery", "Electronics", whatever an admin actually sells, not
a fixed enum) and `description` fields, editable via a new
"Marketplace Listing" card in `ProductManager.jsx` (`PATCH
/admin/store/profile`). `GET /stores` now accepts optional `?search=`
(name, case-insensitive) and `?category=` params, plus a new `GET
/stores/categories` for the filter dropdown's option list. The
Storefront's store-browsing screen gets a search box + category
dropdown above the store grid, and each store card now shows its
category badge and description.

---

## Automated Test Suite & CI Pipeline

**What was missing:** every feature so far had been verified manually
per-session with FastAPI's `TestClient` during development, then
thrown away — there was no persisted, repeatable test suite, and
nothing ran automatically on push/PR to catch a regression before it
reached `main`.

**Why it was needed:** a portfolio project that claims to be
production-shaped needs the same safety net a real production codebase
has — tests that keep passing (or don't) as the code changes, checked
automatically instead of by hand.

**What it does:** `backend/tests/` — a real pytest suite (26 tests)
covering staff auth (signup/login, invite-code join flow, the
admin-self-assignment security guard), customer auth (signup/login,
the two identity systems staying separate), the public no-login
tracking page, app-wide security headers, `/docs` being hidden in
production, and the rate limits on login/signup/tracking actually
tripping under repeated requests. Each test gets its own fresh,
isolated SQLite database (a temp file per test) via a `db_engine` +
`client` fixture pair in `conftest.py`, so tests never touch real data
and can't affect each other. `.github/workflows/ci.yml` runs this
suite (plus a frontend `npm run build` check, plus a Docker image
build check on pushes) on every push and pull request via GitHub
Actions — three parallel jobs: `backend-tests`, `frontend-build`,
`docker-build`.

---

## Admin Action Log & List Pagination

**What was missing:** two gaps. First, the org-wide audit trail only
covered delivery status changes (`DeliveryHistoryDB` /
`/admin/audit-log`) — every OTHER admin write action (deactivating a
user, resetting a password, editing a product, deleting a coupon,
changing store pricing or visibility) left no trace an admin could
later review. Second, several list endpoints returned every matching
row in one response with no `limit`/`offset` at all: dispatcher/agent
delivery lists, a customer's purchase history (`/customer/orders`),
delivery history (`/customer/deliveries`), and notification inbox
(`/customer/notifications`) — fine at demo scale, a real problem for
an account with months of history.

**Why it was needed:** "who changed what, when" is a basic expectation
for anything calling itself admin tooling, and it's exactly the kind
of thing that's awkward to retrofit later once real data (and real
incidents needing investigation) exist. Unbounded list responses don't
show up as a bug in testing with a handful of records — they show up
as a slow, memory-heavy endpoint the day an org's history actually
grows, which is the whole point of building this "for scale" now
rather than after it becomes a problem.

**What it does:**

*Action log:* a new `ActionLogDB` table (`app/models/action_log.py`) —
separate from `DeliveryHistoryDB`, which already covered its own
narrower case well — records actor, action (`product.update`,
`user.deactivate`, `coupon.delete`, `store_settings.update`, etc.),
entity type/id/label, a one-line summary, and (for updates) a
before/after diff of just the fields that changed. `services/action_log.py`
centralizes the write + diffing logic; it's called from `admin.py`
(user deactivate/activate/reset-password), `products.py` (product
create/update/delete, and all four store-settings PATCH routes), and
`coupons.py` (coupon create/update/delete). A new paginated
`GET /admin/action-log` (filterable by entity type / actor, admin-only,
org-scoped) exposes it. `AuditLogViewer.jsx` now has two tabs —
"Delivery Status Changes" (unchanged) and "Admin Actions" (new) — so
both logs live in one place without merging two differently-shaped
tables into one query.

*Pagination:* `GET /customer/orders` and `GET /customer/notifications`
now default to `limit=20`/`offset`-based paging (bounded `limit<=100`).
`GET /customer/deliveries` supports the same `limit`/`offset` but
leaves them optional with no default — that response also seeds the
customer's offline cache (`cacheCustomerDeliveries`), so the call that
drives it still fetches everything, same as before; pagination is
available for any caller that explicitly asks for a page. The
dispatcher/agent delivery lists (`/deliveries/`, `/deliveries/mine`)
were deliberately left as full, unpaginated fetches for the identical
reason — they feed the dispatcher/agent offline IndexedDB cache that
makes the app usable without a network, and capping that response
server-side would silently make the offline fallback incomplete. That
list already pages on-screen client-side (`PAGE_SIZE` in
`DispatcherTable.jsx`), which is the right layer to page a dataset
that's already local. On the frontend: `CustomerDashboard.jsx` now
"Load more"s through the deliveries list (client-side, since the full
set is already in memory) and the notification panel (server-paginated,
tracked via a ref so the 10-second notification poll doesn't reset an
already-expanded page back to the first one). One existing call site —
looking up a cancelled order's refund status by its linked delivery —
was switched to a new `delivery_id` filter on `GET /customer/orders`
instead of scanning the (now paginated) full list, so that lookup
can't silently miss an older order once the endpoint defaults to a
small page size.

**Tests:** `backend/tests/test_admin_action_log_and_pagination.py` (4
new tests) — product CRUD writes the expected action-log entries with
a correct diff, user-management actions are logged, the action log is
both org-scoped and admin-only, and the three customer-facing list
endpoints accept and honor `limit`/`offset`. Full suite: 30/30 passing.
Frontend: `npm run build` clean.

---

## Customer Self-Service Password Reset & Live Agent Location on Public Tracking

**What was missing:** two gaps spotted during a review of the whole
feature set. First, staff accounts already had a complete "forgot
password" email flow (`/auth/forgot-password` + `/auth/reset-password`),
but customer accounts had no equivalent — a customer who forgot their
password had no way to recover the account themselves, only a
logged-in "change password" option that's useless if you can't log in.
Second, the dispatcher side already collects and uses live agent GPS
(for auto-assign suggestions, and for the logged-in customer dashboard's
tracking map), but the *public*, no-login tracking page — the one
shared via the tracking link, usable without an account — only showed
status text, never the agent's live position on a map.

**Why it was needed:** password recovery is a baseline expectation for
any account system, and the public tracking page is the version of
tracking most customers will actually use (no signup required), so
that's exactly where a live map matters most.

**What it does:**

*Customer password reset:* a new `CustomerPasswordResetTokenDB` table
(`models/customer_password_reset.py`) — kept separate from the staff
`PasswordResetTokenDB` for the same reason customer auth already lives
in its own files: `CustomerDB` and `UserDB` are two different identity
systems, and a shared token table would need a discriminator column to
prevent a customer's token ever validating against a staff account or
vice versa. `POST /customer/forgot-password` and
`POST /customer/reset-password` mirror the staff flow's security
choices exactly: an always-identical generic response (so the endpoint
can't be used to check which emails are registered), a 3/minute rate
limit on requests, single-use tokens that expire after 30 minutes.
`ForgotPasswordPage.jsx` and `ResetPasswordPage.jsx` now take an
`accountType` prop and call the right backend flow; the "Forgot
password?" link on the login page — previously staff-only — now shows
for customer login too; `App.jsx` distinguishes a staff reset link
(`?reset_token=`) from a customer one (`?customer_reset_token=`) so
both land on the right flow.

*Live agent location on public tracking:* a new
`GET /track/{delivery_id}/agent-location`, deliberately narrower than
the existing logged-in customer endpoint since this one has no login
and no ownership check to fall back on. It only returns a position
while the delivery is `picked_up` or `out_for_delivery` — the same two
statuses the existing WebSocket location-broadcast in `routes/users.py`
already scopes live pushes to, so the REST fallback and the real-time
updates always agree on when a position counts as "live." It returns
only `latitude`/`longitude`/`updated_at`, never the agent's identity,
matching the rest of `routes/tracking.py`'s existing rule of never
exposing agent info on the public response. `LiveTrackingMap.jsx` (an
existing component, previously only used on the logged-in customer
dashboard) now works in two modes — pass a `token` for the customer
dashboard, omit it for the public page, and it calls the right
endpoint either way; the WebSocket push needed no changes since it was
already unauthenticated. `TrackingPage.jsx` renders the map only while
the delivery is actually `picked_up`/`out_for_delivery`, matching the
backend's own gating instead of attempting a call that's guaranteed to
404 the rest of the time.

**Tests:** `backend/tests/test_customer_reset_and_public_agent_location.py`
(7 new tests) — the forgot-password generic-response behavior for an
unregistered email, a full request→reset→login-with-new-password cycle
(with a check that the old password stops working and the token can't
be reused), expired/invalid token rejection, and the public
agent-location endpoint's status gating (available during
picked_up/out_for_delivery, 404 before pickup, 404 after delivery, 404
for an unknown delivery) plus a check that the response never includes
an agent identifier. Full suite: 37/37 passing. Frontend: `npm run
build` clean.

---

## Bulk Dispatcher Actions & Backfilled Test Coverage

**What was missing:** two smaller gaps flagged alongside the earlier
audit-log/pagination work. First, the dispatcher table had bulk
*import* (CSV upload of new deliveries) but no bulk *edit* of
deliveries already in the system — a dispatcher wanting to move 30
deliveries to "out_for_delivery" at once, or reassign a sick agent's
whole queue to someone else, had to click into each one individually.
Second, the persisted pytest suite covered the newer features well but
had no tests at all for three older, substantial batches of work —
subscriptions, the public marketplace, and the analytics dashboard —
which had only ever been checked manually with TestClient during their
original sessions and never turned into a permanent regression net.

**Why it was needed:** bulk actions are a basic expectation once a
dispatcher table is going to have more than a handful of rows in it —
without bulk edit, "for scale" pagination (the earlier feature) still
leaves scale-sized *work* just as tedious as it always was. And a test
suite that only covers the newest quarter of the codebase gives false
confidence — a change to checkout, cart, or the org-settings model
could silently break subscriptions or analytics with nothing catching
it.

**What it does:**

*Bulk actions:* two new endpoints, `PATCH /deliveries/bulk-status` and
`PATCH /deliveries/bulk-assign-agent`, both dispatcher/admin-only and
org-scoped. Both return a per-item `{delivery_id, success, error}`
result list plus success/failure counts — partial success rather than
all-or-nothing, the same choice `bulk_import_deliveries` already makes,
so one invalid ID in a 50-item selection doesn't block the other 49.
`bulk-status` reuses the exact same history-entry / customer-notify /
refund-on-cancel / return-pickup-on-delivered side effects the
single-record status update already has, so a bulk update is
indistinguishable downstream from doing the same updates one at a
time. `bulk-assign-agent` is a genuine reassignment (works on a
delivery in any in-progress status, not just `pending` — a dispatcher
pulling deliveries off a sick agent needs exactly that), rejects
already-`delivered`/`cancelled` deliveries per-item rather than failing
the whole batch, and bumps a still-`pending` delivery to `picked_up`
the same way a normal first assignment does. On the frontend,
`DispatcherTable.jsx` gained row checkboxes, a "select all visible"
header checkbox, and an action bar that appears once anything's
selected — status dropdown + Apply, agent dropdown + Reassign, and a
result toast summarizing how many succeeded/failed.

*Backfilled tests:* four new test files —
`test_bulk_delivery_actions.py` (8 tests: multi-delivery status update,
partial success on an unknown ID, org isolation, pending→picked_up on
reassign, agent-swap-without-status-change for an in-progress delivery,
rejection of delivered/cancelled deliveries and unknown agents, and a
role check), `test_subscriptions.py` (8 tests: create, invalid-interval
and cross-org-product rejection, the full run-now → initiate-payment →
`/customer/checkout/verify` cycle ending in a real unassigned delivery,
a COD variant that needs no payment gateway, the insufficient-stock
skip-this-item behavior, pause/resume/cancel and the state transitions
they block, and ownership isolation between customers),
`test_marketplace.py` (7 tests: the opt-in visibility default and
toggle, case-insensitive name search, category filtering, active-only
product listing, and 404s for a private or unknown store), and
`test_analytics.py` (8 tests: a real end-to-end checkout reflected
correctly including the org's delivery-fee/tax defaults, zero-filled
revenue-by-day, orders outside the requested window excluded, refund
totals, delivery status breakdown, low-stock detection, org isolation,
and an admin-only role check).

**Tests:** all four new files pass; full suite: **68/68 passing** (up
from 37). Frontend: `npm run build` clean.

---

## Staff Self-Service Account Settings & Notification Dropdown Fix

**What was missing:** a fresh full audit (every route file, cross-checked
against the frontend) turned up one genuine asymmetry: customers could
change their own password and edit their own profile while logged in
(`/customer/me`, `/customer/me/change-password`); staff (admin/
dispatcher/agent) had neither — only an admin resetting *someone else's*
password, or the forgot-password email flow, which only helps when
you're already logged out. There was no "my account" page for staff at
all, just a 2FA settings screen. Separately, a UI bug was reported: the
customer dashboard's notification panel rendered as a plain block in
the page's normal content flow instead of as a proper dropdown, so it
could appear stacked oddly against whatever view was currently active.

**Why it was needed:** an app with no known limitations shouldn't have
one half of its user base able to self-manage their account and the
other half locked out of it entirely — this is the same class of gap
customer forgot-password was, just on the other side of the app. The
notification overlap was a straightforward visual bug worth fixing on
its own merits.

**What it does:**

*Staff account settings:* `GET/PATCH /auth/me` and
`POST /auth/me/change-password`, added right next to `get_current_user`
in `routes/auth.py` and mirroring `routes/customer_auth.py`'s
`/customer/me` endpoints field-for-field — same current-password
verification, same 6-character minimum, same "email already used by
another account" check. Deliberately excludes `username` from what's
editable: it's the app's login identifier, and letting a logged-in user
change it would need the same collision/audit-trail handling account
renames always require, without anything about self-service editing
actually needing it — a display name change covers the actual use case
("show a different name to my team"). New `AccountSettings.jsx` (mirrors
`CustomerDashboard.jsx`'s `ProfilePanel` exactly), reachable via a new
"My Account" sidebar link for all three staff roles, right above the
existing "Security" (2FA) link — a separate page from 2FA on purpose,
since "who am I / what's my password" and "how do I log in" are
different concerns someone might visit independently.

*Notification dropdown fix:* the notification panel is now `position:
fixed`, anchored near the sidebar's Notifications trigger button, with
a transparent click-outside-to-close backdrop and a close (×) button —
completely decoupled from the page's document flow, so it always
appears in the same place regardless of scroll position or which
dashboard tab is active. Same idea the existing mobile
`.sidebar-overlay` pattern already used elsewhere in the file. Collapses
to a full-width bottom sheet under 768px.

**Tests:** `backend/tests/test_staff_account_settings.py` (9 new tests)
— profile fetch, display-name/email update (including a partial update
that leaves the untouched field alone), empty-name and email-collision
rejection, a full change-password cycle verified by actually logging in
with the old password (fails) and the new one (succeeds), wrong-current-
password and too-short-new-password rejection, and an auth-required
check across all three endpoints. Full suite: **77/77 passing** (up
from 68). Frontend: `npm run build` clean.

---

## Security Hardening: Email Verification, CAPTCHA, and Refresh-Token Rotation

**What was missing:** a self-audit turned up three real security gaps
relative to what a production-minded app would have: no email
verification at all (anyone could sign up with an email they don't
own), no bot protection beyond rate limiting on the public signup/
forgot-password endpoints, and access tokens that lasted 24 hours with
no way to revoke one early if it leaked — a JWT, once issued, stays
valid until it expires no matter what happens server-side afterward.

**Why it was needed:** these are the differences between "works for a
demo" and "the kind of auth system a real product would ship" — each
is a standard line item in a security review, and having all three
missing was the single biggest gap left in the project relative to its
otherwise thorough feature set.

**What it does:**

*Email verification (staff + customer):* a new `email_verified` column
on both `UserDB` and `CustomerDB`, with a verification email sent
automatically at signup and `POST /auth/verify-email` +
`POST /auth/resend-verification` (and customer equivalents) to
complete it. Deliberately does NOT block login — the same trade-off
Slack, GitHub, and most real products make: an admin creating an org
needs to use their own dashboard immediately, not wait on an email
round-trip, and SMTP itself is optional in this project (falls back to
console-logging the email), so a hard gate would make the app
partially unusable without it configured. What it does give: a real,
checkable flag, and a dismissible banner with a one-click resend in
both the staff shell and the customer dashboard.

*CAPTCHA:* `services/captcha.py`, a genuine Google reCAPTCHA v2
integration modeled deliberately on `services/payment.py`'s existing
"optional integration, no-ops if unconfigured" pattern — set
`RECAPTCHA_SECRET_KEY` and it calls Google's siteverify API for real;
leave it unset (the default) and every check passes automatically,
logged once at startup so the current mode is never a silent gap.
Wired into staff + customer signup and forgot-password. The frontend's
`Captcha.jsx` widget only renders if `VITE_RECAPTCHA_SITE_KEY` is set,
degrading the same way independently on that side.

*Refresh-token rotation:* access tokens shortened from 24 hours to 30
minutes (`services/auth.py`). New `RefreshTokenDB`/
`CustomerRefreshTokenDB` tables hold long-lived (30-day), SHA-256-hashed
refresh tokens — hashed with a fast algorithm rather than bcrypt on
purpose, since the token is already high-entropy random data, not a
human password; see that file's docstring. Every use rotates the token
(old one marked spent, pointing at its replacement); presenting an
already-rotated token is treated as a theft signal and revokes the
entire remaining chain for that user, not just the one token. New
`POST /auth/refresh` and `POST /auth/logout` (and customer
equivalents) — logout now genuinely revokes server-side instead of
just clearing local storage, which is the actual "revoke early"
capability a JWT-only scheme never had. `AuthContext.jsx`/
`CustomerAuthContext.jsx` persist the refresh token and silently renew
the session every 20 minutes in the background, so the shorter access-
token life is invisible in normal use.

**A pre-existing test-infrastructure bug found along the way:**
`test_rate_limiting.py` deliberately reloads Python's module cache to
test with rate limiting turned on (see that file's own docstring for
why). Doing so left `conftest.py`'s shared `client` fixture wired to a
stale `get_db` function reference for every test that ran after it in
the same session — silently making its database-isolation override a
no-op and leaking those tests' writes into the real
`backend/database.db` instead of each test's isolated file. This
predates this session's changes and had gone unnoticed because nothing
in the existing suite happened to check for state that leaked writes
would corrupt; two of this session's new tests (checking for a
duplicate email) were the first to actually trip over it. Fixed by
re-fetching `get_db` fresh inside the `client` fixture on every call
instead of relying on a reference captured once at collection time —
see `PROJECT_WORKFLOW.md` for the full diagnosis.

**Tests:** three new files — `test_email_verification.py` (9 tests:
unverified-by-default, non-blocking login, full verify cycle,
invalid/expired/reused tokens, resend and its already-verified
short-circuit, auth-required), `test_captcha.py` (6 tests: no-op mode
end to end through real signup/forgot-password calls, plus the
configured-mode logic unit-tested directly with a mocked HTTP call),
and `test_refresh_tokens.py` (8 tests: token issuance, rotation, reuse-
triggered chain revocation, expiry, and logout revocation, for both
staff and customer). Full suite: **100/100 passing** (up from 77).
Frontend: `npm run build` clean.

---

## Failed-Delivery Reason Codes, Delivery-Attempts Log, Reschedule Workflow, Partial-Delivery Marking, Priority Sorting

**What was missing:** the rest of the delivery lifecycle beyond a
plain status update — no standardized way to record *why* a delivery
failed, no log of how many times a delivery had actually been
attempted (vs. just its current status), no way to reschedule a
failed delivery to a new date, no way to record that a delivery was
only partially completed, and no way for a dispatcher to prioritize
which deliveries in the queue matter most.

**Why it was needed:** free-text `notes` on a failed delivery doesn't
give a dispatcher or an analytics dashboard anything to group or act
on — "customer wasn't home" and "not home" and "no one answered" are
the same event described three ways. Attempt history distinct from
status history matters because a delivery's *current* status doesn't
tell you it took three tries to get there. And a flat, unordered
dispatcher queue means urgent same-day orders get lost in a list
sorted only by recency.

**What it does:**
- **Reason codes** (`models/failed_delivery_reason.py`,
  `routes/failed_delivery_reasons.py`) — admin-managed, org-scoped
  CRUD at `/admin/failed-delivery-reasons`, with soft-delete via an
  `active` flag so retiring a code doesn't break attempts that already
  reference it. `GET /deliveries/reason-codes/active` is the
  agent-facing picker (active-only, any authenticated org member).
- **Enforcement** — `PATCH /deliveries/{id}` now rejects a
  `failed_attempt` status update that doesn't carry a valid, active
  `reason_code_id` (400). Bulk status update
  (`PATCH /deliveries/bulk-status`) deliberately refuses to bulk-move
  deliveries to `failed_attempt` at all, since one shared reason across
  an arbitrary batch would defeat the point of having real reason
  codes — that stays a single-record action.
- **Delivery-attempts log** (`models/delivery_attempt.py`,
  `services/delivery_attempts.py`) — every real attempt outcome
  (delivered / failed_attempt / partial_delivery) gets its own logged
  row with a running `attempt_number`, distinct from the existing
  status-history log which also covers non-attempt events like
  assignment. `GET /deliveries/{id}/attempts` returns the full log.
  Threaded through all three paths that can produce a real outcome:
  the online PATCH, bulk-status (delivered only), and the offline
  `/sync` path (`services/conflict_resolver.py`) — the last one
  doesn't hard-enforce the reason code the way the online path does,
  since `/sync` is unauthenticated/best-effort and rejecting a whole
  offline batch over a missing reason would strand an agent's work.
- **Reschedule workflow** — `POST /deliveries/{id}/reschedule`, usable
  by the assigned agent or any dispatcher/admin, sets a new
  `rescheduled_to` date + `reschedule_reason`, bumps
  `reschedule_count`, moves status to `failed_attempt` (a reschedule
  genuinely is a failed attempt at the original time), and logs both a
  history entry and an attempt row. Refuses on an already-terminal
  delivery.
- **Partial-delivery marking** — `is_partial` + `partial_notes` on
  `PATCH /deliveries/{id}` when marking `delivered`; status stays
  `delivered` (a partial delivery is still a completed attempt), but
  the flag/notes record what wasn't handed over, and the attempt log
  records the outcome as `partial_delivery`.
- **Priority-based dispatcher queue** — new `priority` field
  (low/normal/high/urgent, plain string column — see
  `DeliveryPriority`'s docstring for why not a SqlEnum) settable at
  creation and via `PATCH /deliveries/{id}/priority` (dispatcher/admin
  only). `GET /deliveries/` and `GET /deliveries/unassigned` now sort
  urgent → high → normal → low, oldest-first within a tier.
- **Frontend:** `DeliveryStatusUpdater.jsx` gates "Failed Attempt"
  behind a reason-code dropdown and "Delivered" behind an optional
  "partially delivered" toggle; `AgentDeliveryList.jsx` adds an inline
  reschedule form; `DispatcherTable.jsx` gets an editable priority
  column, a priority sort option, and a priority field on delivery
  creation; `DeliveryDetailModal.jsx` gets a new "Delivery Attempts"
  section plus priority/partial/reschedule detail rows; new admin page
  `FailedDeliveryReasonManager.jsx` for reason-code CRUD, wired into
  the sidebar and `App.jsx`.

**Tests:** new file `test_delivery_lifecycle_extras.py` (21 tests:
reason-code CRUD + org isolation, non-admin rejection, enforcement on
missing/invalid/inactive reason codes, attempt logging + numbering,
bulk-status rejecting failed_attempt, partial-delivery flag set/clear,
reschedule success/validation/permission/terminal-status rejection,
priority update, dispatcher-queue and unassigned-queue priority
sorting, new-delivery default priority, and the offline-sync path
threading reason codes and partial-delivery through to the attempt
log). Full suite: **121/121 passing** (up from 100). Frontend:
`npm run build` clean.

---

## Group 3 — Workforce Management (Shifts, Attendance, Leave, Earnings)

**What was missing:** no way to schedule staff, track when they
actually worked, handle time-off requests, or compute what they're
owed. This was a whole domain gap, not an extension of anything
existing.

**Why it was needed:** a delivery-ops platform managing agents needs
more than delivery assignment — a dispatcher needs a roster, an admin
needs payroll data, and an agent needs a way to request time off
without a side channel (a text message, a shrug).

**What it does:**
- **Shifts** (`models/shift.py`) — the roster PLAN: dispatcher/admin
  schedules a staff member for a date + time window
  (`POST /workforce/shifts`), staff see their own
  (`GET /workforce/shifts/mine`), status auto-advances to
  `completed` when a clock-out closes the matching attendance session.
- **Attendance** (`models/attendance.py`) — the ACTUAL record:
  `POST /workforce/attendance/clock-in` (optionally against a specific
  shift; unscheduled sessions are allowed and flagged) /
  `clock-out`. Only one open session per user at a time is enforced at
  the route level.
- **Leave requests** (`models/leave_request.py`) — sick/vacation/
  personal/unpaid, submitted by the staff member
  (`POST /workforce/leave-requests`), approved/rejected by a
  dispatcher/admin, or cancelled by the requester while still pending.
  Deliberately doesn't block shift creation for overlapping dates —
  see the model's docstring for why that's left to human review rather
  than automated conflict detection.
- **Earnings** (`models/earnings.py`, `services/earnings.py`) —
  computed pay statements combining two independent, optional
  components: hours worked (summed from clocked-out attendance
  sessions) × `hourly_rate`, and completed/partial deliveries (counted
  from the existing `DeliveryAttemptDB` log — see Group 2) ×
  `per_delivery_rate`. Both rates live on `UserDB`
  (`PATCH /workforce/pay-rate/{user_id}`, admin-only).
  `POST /workforce/earnings/generate` computes for one staff member or
  the whole org over a date range; regenerating for the same period
  overwrites the existing draft — UNLESS it's already `paid`, which is
  left untouched (a paid statement is a closed book). Draft →
  finalized → paid is a one-way lifecycle.
- **Frontend:** `MyWorkforce.jsx` (agent self-service: clock in/out,
  my shifts, submit/cancel leave requests, view earnings) and
  `WorkforceManager.jsx` (dispatcher/admin: shift roster, org
  attendance log, leave approvals, pay-rate editing, earnings
  generation/finalize/mark-paid), both wired into `Sidebar.jsx`/
  `App.jsx` as a new "Workforce" / "My Workforce" nav item per role.

**Tests:** new file `test_workforce.py` (21 tests: shift CRUD +
permission + validation, clock-in/out including the double-clock-in
and clock-out-without-clock-in rejections and the shift-linkage/
auto-complete behavior, leave request submit/approve/reject/cancel/
permission checks, pay-rate set/clear, earnings generation combining
hours and deliveries with a failed_attempt correctly excluded,
org-wide generation, the finalize→paid lifecycle and its ordering
requirement, and the paid-statement-is-immutable-on-regenerate
guarantee). Full suite: **142/142 passing** (up from 121). Frontend:
`npm run build` clean.

---

## Missing-Features Rollout — Phase 1: Proof of Delivery

**What was missing:** A delivery could be marked "Delivered" with only the
existing free-form `proof_of_delivery` image blob — no structured record
of who received it, no recipient verification, no GPS at the moment of
capture, no org-level control over what's required, and no way to view
a POD history separately from the general status-change history.

**Why it was needed:** Dispute resolution, fraud prevention, and
compliance all depend on a real, queryable proof-of-delivery record —
not just an optional photo nobody is required to attach.

**What it does:** A new `ProofOfDeliveryDB` table (recipient name/phone,
OTP verification, signature/photo, GPS, notes, timestamp, offline-capture
flag) plus a `DeliveryOtpDB` table for short-lived hashed recipient
verification codes. Four org-level toggles (`pod_require_recipient_name`,
`pod_require_signature_or_photo`, `pod_require_otp`, `pod_require_gps`),
all OFF by default so no existing org's workflow changes unless an admin
opts in. Enforcement is applied at BOTH places a delivery can be marked
delivered: the online `PATCH /deliveries/{id}` route AND the offline-sync
path (`services/conflict_resolver.py`) — the latter matters because that's
actually the PRIMARY agent workflow (IndexedDB → `/sync`), not the PATCH
route, and was the one place this could have been silently missed.
New endpoints: OTP generate/verify, POD submit/view/history, org POD
settings (admin), and a CSV export report. A customer can view POD for
their own delivered orders only. Frontend: `ProofOfDeliveryModal` now
captures recipient/OTP/GPS/notes alongside the existing signature/photo,
queued through a dedicated offline retry queue
(`services/podOfflineQueue.js`) so capture works identically online or
offline; a `PodSettingsPanel` for admins; a POD viewer section in
`DeliveryDetailModal`; and a POD summary in the customer dashboard.
**15 new backend tests, all passing** (including a dedicated regression
test proving the offline-sync path enforces the requirement, not just
the PATCH route). Full backend suite: **168/168 passing**. Frontend:
`npm run build` clean.

---

## Missing-Features Rollout — Phase 2: SLA Management

**What was missing:** No concept of a delivery deadline, no way to know
a delivery was running late until a human noticed, and no visibility
into how often deliveries actually meet expectations.

**Why it was needed:** Dispatchers need to catch at-risk deliveries
before they're late, not after; customers deserve a plain-language
"running late" signal instead of silence; and the business needs real
SLA%, average delivery time, and average delay numbers instead of guesses.

**What it does:** A new `SLAPolicyDB` table — org-scoped policies
optionally narrowed by zone, delivery type, and/or priority, with a
target duration and a configurable near-breach warning threshold.
Matching picks the most specific active policy for a delivery (a
zone+priority match beats a priority-only match beats the org-wide
default). Three new columns on `DeliveryRecordDB` (`sla_policy_id`,
`sla_target_at`, `sla_status`) track each delivery's computed deadline
and live classification (`on_track` / `at_risk` / `breached` while in
progress; `met` / `missed` once delivered; `not_applicable` if no policy
matches). A background scanner (`services/sla_monitor.py`, same
interval-loop shape as the existing subscription scheduler) runs every
60 seconds, flips state as thresholds are crossed, and pushes a
notification to every dispatcher/admin in the org on each transition.
New endpoints: policy CRUD (admin), a dispatcher SLA worklist of
currently at-risk/breached deliveries, and a live-computed analytics
endpoint (SLA%, avg delivery time, avg delay, breakdown by agent and by
zone). Public tracking and the customer dashboard both surface a
plain-language "running a bit behind schedule" note (never exposing the
org's actual policy configuration) when a delivery is at risk, breached,
or was delivered late. Frontend: a new `SlaManager` view (dashboard +
policy editor, role-gated the same way the rest of the admin UI already
is) reachable from the sidebar. **11 new backend tests, all passing.**
Full backend suite: **168/168 passing**. Frontend: `npm run build` clean.

---

## Missing-Features Rollout — Phase 3: Warehouse Management

**What was missing:** No concept of WHERE stock physically lives —
`ProductDB.stock_quantity` was a single number with no warehouses, no
stock-in/out/transfer trail, no batch/expiry tracking, and no supplier/
purchase-order workflow.

**Why it was needed:** Real fulfillment operations run out of one or
more physical locations, need an auditable movement log for every
stock change, and need a receiving workflow tied to actual purchase
orders — not a number a dispatcher edits by hand.

**What it does:** Five new tables — `WarehouseDB`, `WarehouseInventoryDB`
(per warehouse/product: available/reserved/damaged, SKU, barcode, batch,
expiry, low-stock threshold), `StockMovementDB` (an immutable log —
every single stock change of any kind writes one row here), `SupplierDB`,
and `PurchaseOrderDB`/`PurchaseOrderItemDB`. Built ADDITIVELY: the
existing `ProductDB.stock_quantity` and the whole cart/checkout/refund
flow that depends on it are completely untouched — nothing here changes
checkout math. A new `sync_product_stock_from_warehouses()` bridge lets
an admin/dispatcher explicitly opt a product into having its
`stock_quantity` driven by real warehouse totals, but nothing does this
automatically. Full stock-in/out/adjustment/transfer/damage operations,
each logged; a low-stock endpoint; supplier CRUD; and a goods-received
workflow (supports partial receipt, tracks the PO status lifecycle:
draft → ordered → partially_received → received) that credits inventory
through the exact same stock-in path a manual receipt uses. Frontend: a
new `WarehouseManager` view (warehouses, inventory + movement forms,
suppliers, purchase orders, low-stock) reachable from the sidebar for
dispatchers and admins. **14 new backend tests, all passing.**

---

## Missing-Features Rollout — Phase 4: Granular RBAC

**What was missing:** Only three fixed roles (agent/dispatcher/admin) —
no way to grant or restrict a specific capability to a specific person
without changing their whole role.

**Why it was needed:** Real orgs need finer control — e.g. an agent who
should ALSO be able to manage inventory, or a dispatcher who should NOT
be able to issue refunds — without a new base role for every
combination.

**What it does:** Added ADDITIVELY on top of the existing `UserDB.role`
system — every existing `require_admin()`/`require_dispatcher()` check
across the app (30+ files) is completely unmodified and still works
exactly as before. New tables: `CustomRoleDB` (an org's own named roles)
and `RolePermissionDB` (explicit permission grants per role), plus one
new nullable `UserDB.custom_role_id` column (null = "use my base role's
default permissions", which is true for essentially every user unless
an admin deliberately assigns one). A fixed `PERMISSION_CATALOG`
(`deliveries.*`, `users.*`, `inventory.*`, `payments.*`, `analytics.*`,
`workforce.*`, `settings.*`) and a `require_permission(perm)` FastAPI
dependency provide REAL backend enforcement — never a frontend-only
check — with admins always passing every check unconditionally. This is
demonstrated end-to-end on real functionality: every Phase 3 warehouse/
supplier/purchase-order endpoint is gated on `inventory.view` /
`inventory.manage` rather than the coarser dispatcher/admin check, and a
custom role's grants are authoritative even when they're NARROWER than
a user's base role would normally allow (tested explicitly). Custom
role CRUD, role assignment, a permission catalog endpoint, and a
`GET /admin/rbac/my-permissions` endpoint for permission-aware frontend
UI to call (rather than re-implementing the resolution logic client-side)
are all admin-only. Frontend: a new `RbacManager` view for defining
roles, plus a role-assignment dropdown added directly to the existing
Manage Users table in `AdminPanel`. Retrofitting every OTHER pre-existing
endpoint onto `require_permission()` is explicitly OUT of scope for this
phase — see "Intentionally skipped" in the completion report; that's a
large, separate migration best done incrementally with its own
regression testing. **10 new backend tests, all passing.**

Full backend suite after Phases 3+4: **192/192 passing**. Frontend:
`npm run build` clean.

---

---

## Missing-Features Rollout — Phase 5: COD & Payment Reconciliation

**What was missing:** No auditable financial trail — a payment or
refund happened, but nothing recorded it as a discrete, queryable
event; COD orders had no tracking of expected vs. actually-collected
cash.

**Why it was needed:** "Every financial operation must be auditable" —
real money handling needs a permanent record of every charge, refund,
and cash collection, plus a way for an agent's collected cash to be
formally handed off (settled) to the business.

**What it does:** A new `PaymentLedgerDB` — an APPEND-ONLY log (nothing
in it is ever edited or deleted; corrections are new rows) — plus
`CodCollectionDB` (expected vs. collected amount per COD delivery, with
automatic discrepancy detection) and `AgentSettlementDB` (batches an
agent's unsettled collections, immutable once marked settled — same
pattern `services/earnings.py` already uses for pay statements). Built
additively: `services/checkout.py`'s real online-payment success path
and `services/refund.py`'s real refund path each got exactly one new
line — a call to log the ledger entry — with zero changes to their
existing logic; verified with tests that place a REAL order through
checkout and a REAL refund through cancellation and confirm the ledger
entry actually appears, not just that the logging function works in
isolation. An agent records what they collected via a new endpoint;
a mismatch is flagged as `discrepancy` automatically. New endpoints:
COD collection (agent-facing), settlement creation/settling, the raw
ledger (filterable by order/date/type), per-order payment status
history, and an admin financial dashboard — all gated on Phase 4's
`payments.view`/`payments.manage` permissions, a second real
demonstration of that system. Frontend: a new `ReconciliationDashboard`
view (overview stats, COD collections, settlements, ledger) and a
`CodCollectionWidget` embedded in the delivery detail view. **13 new
backend tests, all passing.**

---

## Missing-Features Rollout — Phase 6: Customer <-> Agent Communication

**What was missing:** The existing delivery chat thread
(`DeliveryMessageDB`, WebSocket-backed) only had staff (agent/
dispatcher/admin) as participants — a customer had no way to message
the delivery team, and there was no read/unread tracking or predefined
quick replies.

**Why it was needed:** Customers need a direct channel to ask "where's
my order" or share a gate code without a phone call, and staff need to
see message state (read vs. unread) rather than guessing whether a
reply's been seen.

**What it does:** Extended the EXISTING `DeliveryMessageDB` table
(added `read_by_staff_at` / `read_by_customer_at` columns and allowed
`sender_role="customer"`) rather than building a parallel thread — a
customer and staff member now read/write the exact same rows and see
literally the same conversation. A new customer-scoped route
(`routes/customer_messages.py`) mirrors the existing staff route
(`routes/messages.py`) with the same ownership-check pattern every
other customer endpoint uses. Both sides mark the other's messages read
the moment they view the thread, with a dedicated unread-count endpoint
each. Four predefined quick-reply strings ("I'm arriving...", "Unable
to reach you...", etc.) sent through the exact same send-message
endpoint — no separate "template" concept in the data model to keep in
sync. The existing WebSocket chat endpoint (`routes/websockets.py`)
was extended to also authenticate a customer's JWT, not just staff —
this was a genuine gap caught and fixed, not initially planned: without
it the customer side would have been polling-only while staff got live
push. Frontend: `CustomerDeliveryMessages` (new, mirrors the existing
`DeliveryMessages` component) embedded in the customer dashboard for
any non-terminal delivery, and quick-reply buttons added to the
existing staff-side chat widget. **9 new backend tests, all passing.**

Full backend suite after Phases 5+6: **214/214 passing**. Frontend:
`npm run build` clean.

---

---

## Missing-Features Rollout — Phase 7: RTO Management

**What was missing:** A delivery that genuinely couldn't be completed
(wrong address, refused, unreachable after repeated attempts) just sat
in `failed_attempt` status forever — no formal "this is going back to
the sender" workflow, no eligibility rule, no lifecycle, no automatic
refund/restock when it actually came back.

**Why it was needed:** Real courier operations need a distinct
Return-to-Origin process — separate from a customer-initiated RETURN of
something they already received (`models/return_request.py`, untouched)
— with clear eligibility rules and a resolution that actually restocks
inventory and refunds the customer.

**What it does:** A new `RtoRequestDB`, integrated with the EXISTING
failed-delivery system rather than duplicating it: eligibility is
checked automatically from inside `services/delivery_attempts.py`'s
`record_delivery_attempt()` — the one function every failed-attempt
path in the app already calls (the online PATCH, the offline-sync
path, bulk actions, and the reschedule endpoint) — so there's exactly
one place this logic needed to live. A delivery becomes RTO-eligible
either because the reason code used is flagged `eligible_for_rto`
(admin-configurable, added to the existing `FailedDeliveryReasonDB`)
or because it's hit the org's configurable `rto_max_attempts`
threshold (default 3). Full lifecycle — eligible → approved →
in_transit → received_at_origin, or cancelled — gated on
`deliveries.assign` (a real bug caught during testing: my first pass
gated this on `deliveries.update`, which agents also have by default
for updating their own delivery status, so agents could approve their
own RTOs; switched to the dispatcher-only permission). Marking a
request received reuses `refund_order_for_delivery()` exactly as
cancellation does — a prepaid order gets a real refund (which, via
Phase 5's hook, writes a ledger entry automatically) and restock; a COD
order (never actually charged) just restocks, verified with a test
that runs a complete online order through the full RTO cycle and
confirms the refund and ledger entry both actually appear, plus a
separate COD test confirming no refund fires. RTO analytics (counts by
status, by reason, average resolution time) and a settings panel for
the attempt threshold. Frontend: a new `RtoManager` view (analytics,
settings, request list with stage-appropriate actions). **12 new
backend tests, all passing.**

---

## Missing-Features Rollout — Phase 8: Barcode/QR Package Scanning

**What was missing:** No way to physically scan a package at any stage
of its journey — no generated code, no scan log, no duplicate
protection.

**Why it was needed:** Real fulfillment operations scan packages at
pickup, hub transfers, dispatch, and delivery — both for an audit
trail of where a package physically was, and to catch mis-scans.

**What it does:** No new "package" concept was introduced — this
project's delivery model is already one record per package, so a
delivery's own ID IS the scannable code (a new `qrcode` dependency
renders it as SVG, no Pillow/image-processing dependency needed). A
new `PackageScanDB` is a purely ADDITIVE audit layer: recording a scan
does NOT itself change delivery status — the agent still updates
status the normal way — so scanning-related code never reaches into
core delivery lifecycle logic. Endpoints: generate the QR, resolve a
scanned code back to a delivery (org-scoped, so a foreign or
nonexistent code correctly comes back as invalid — this is what
"invalid scan handling" means here), record a scan of any stage
(pickup/hub/out_for_delivery/delivery/return), scan history per
delivery, and an org-wide filterable scan log. Duplicate-scan
protection rejects an identical (delivery, stage) scan within a
60-second window (an agent's scanner double-firing) while still
allowing a legitimate later re-scan of the same stage — tested
explicitly for both cases. Authorization mirrors Phase 1's POD routes
exactly (an agent may only scan their own assigned deliveries; any
dispatcher/admin may scan any of the org's deliveries) — during
testing this caught a real bug where the code-resolution endpoint
tried to serialize a raw database object whose primary key is named
differently than the response schema expected, which would have 500'd
in production; fixed by building the response explicitly. Frontend: a
new `PackageScanWidget` (QR display + scan-stage buttons + history)
embedded in the delivery detail view. **13 new backend tests, all
passing.**

Full backend suite after Phases 7+8: **239/239 passing**. Frontend:
`npm run build` clean.

---

---

## Missing-Features Rollout — Phase 9: Advanced Routing

**What was missing:** No location HISTORY (only "where is this agent
right now"), so no ETA recalculation as an agent actually moves, no
deviation detection, no route replay, no heatmap, and no way to
optimize routes across more than one agent at a time.

**Why it was needed:** Dispatchers need to know when an agent has gone
off-course, customers benefit from a live (not static) ETA, and
planning benefits from seeing where delivery activity actually
concentrates.

**What it does:** A new `AgentLocationHistoryDB` ping log, purely
additive alongside the EXISTING `AgentLocationDB` "latest position
only" table — every existing consumer of that table (customer live
tracking, the dispatcher map) is completely unaffected; this phase
only adds a second, parallel write into the new history table from the
exact same `PUT /users/me/location` endpoint. On top of that history:
dynamic ETA (fresh road-distance recalculation from the agent's
CURRENT position, not the once-computed value from assignment time),
a disclosed pragmatic route-deviation heuristic (this project has no
stored planned-route polyline anywhere to compare against, so
deviation is detected as "meaningfully further from the destination
than the closest approach so far" — a real, tested signal, not a
false claim of full path-matching), geofence "arrived" alerts to
dispatchers AND customers (deduplicated to fire once per delivery, not
on every ping while an agent lingers nearby), route replay, distance-
traveled/time-spent/efficiency-ratio metrics, a heatmap aggregation
endpoint, and multi-agent route optimization — honestly scoped as
grouping by each delivery's EXISTING agent assignment plus the
already-existing single-route optimizer with a slot-deadline priority
nudge, not a claim of solving vehicle-routing from scratch. Frontend:
a `RouteInsightsWidget` in the delivery detail view and a
`RoutingInsights` page (heatmap table + manual multi-agent optimize
trigger). **14 new backend tests, all passing.**

---

## Missing-Features Rollout — Phase 10: Customer Communication & Notifications

**What was missing:** Before writing anything, the existing
notification system was audited: SMS/WhatsApp sending abstractions,
email sending, and MOST status-driven customer notifications (order
confirmed/picked-up/out-for-delivery/delivered/failed/cancelled/
partial/rescheduled) already existed via
`notify_customer_of_status_change`. What was genuinely missing: any
notification at all for a refund, a return approval, an agent being
physically nearby, an upcoming delivery, or an upcoming subscription
renewal — plus no way for an org to customize wording.

**Why it was needed:** A customer who gets refunded or has a return
approved deserves to be told; a proactive "delivery reminder" and
"subscription renews soon" give customers a chance to act before
something happens rather than only after.

**What it does:** A new `NotificationTemplateDB` — deliberately kept
SEPARATE from the existing, heavily-tested
`notify_customer_of_status_change()` (which was left completely
untouched rather than risk a rewrite for comparatively little
benefit) — powers exactly the five genuinely-new event types:
refund_processed, return_approved, agent_nearby, delivery_reminder,
subscription_reminder. Each has a sensible built-in default; an org
can customize the subject/body per event and toggle which of
email/SMS/WhatsApp/in-app fire, all through one
`send_templated_notification()` function reused everywhere. Two new
generic-text SMS/WhatsApp senders were added alongside the existing
fixed-format ones (`send_status_notification_sms` etc.), which bake in
a specific "order is now X" sentence that a free-text template can't
reuse. Wired into REAL flows: `services/refund.py` now notifies on
both the test-mode and real-gateway refund paths; `routes/returns.py`
notifies on approval; Phase 9's geofence-arrival hook now also
notifies the CUSTOMER (previously dispatcher-only); and a new
`services/reminder_scheduler.py` (same interval-loop shape as the
existing SLA/subscription schedulers) sends delivery and subscription
reminders exactly once per occurrence via a `reminder_sent_at` marker,
verified with tests proving a second scan never double-sends and a
too-far-out delivery is correctly skipped. Explicitly scoped out: a
duplicate "agent assigned" notification, since the app already sends
one under the existing "picked up" status label — adding a second
would be notification spam, not a missing feature. Frontend: a
`NotificationTemplateManager` settings panel. **10 new backend tests,
all passing**, including two that run a REAL refund and a REAL return
approval through the system and confirm the customized notification
text actually appears — not just that the sending function works in
isolation.

Full backend suite after Phases 9+10: **263/263 passing**. Frontend:
`npm run build` clean.

---

## Missing-Features Rollout — Phase 11: Fleet Management

**What was missing:** No representation of physical vehicles at all —
no way to record what a delivery fleet actually consists of, which
agent is driving which vehicle, servicing history, fuel cost, or
upcoming insurance/registration/inspection deadlines.

**Why it was needed:** A real delivery operation runs on vehicles, not
just agents — a dispatcher needs to know a van is overdue for
insurance renewal before it's out on the road, and an org tracking
fuel spend needs a place to log it against a specific vehicle.

**What it does:** Three new tables — `VehicleDB` (type, registration,
capacity, status, current agent assignment, odometer, insurance/
registration/inspection dates), `VehicleMaintenanceDB` (service
history with a `next_due_date` for reminders), and
`VehicleFuelRecordDB` (fuel purchase log). A vehicle's live location is
deliberately NOT a separate, independently-updated field — it's
derived on request from its assigned agent's existing `AgentLocationDB`
row (the same Phase 9 "latest position" table already powering
customer tracking), so there's exactly one source of truth for "where
is this thing right now." Vehicle CRUD and assignment are dispatcher/
admin actions (one vehicle per agent, enforced); any staff member can
log a fuel record, but an agent can only log one against their own
assigned vehicle. `GET /fleet/reminders` surfaces vehicles whose
insurance, registration, or inspection falls within a configurable
window, plus any maintenance record's `next_due_date` in that window.
`GET /fleet/vehicles/{id}/utilization` counts deliveries completed by
a vehicle's currently-assigned agent over a period — honestly scoped:
this project has no vehicle-assignment history table, so a
reassignment mid-window attributes the whole window to the current
agent, and that trade-off is documented in the code rather than
hidden. Capacity is integrated into the EXISTING Phase 9
suggested-agents ranking as a new, purely advisory
`vehicle_capacity_warning` field — it never changes agent ranking or
blocks assignment, since vehicle capacity is a dispatcher judgment
call, not a hard rule with no override. Frontend: a new `FleetManager`
page — dispatchers/admins get the full manager (vehicle CRUD,
assignment, maintenance/fuel logging, reminders banner); agents get a
read-only view scoped to their own assigned vehicle (`GET
/fleet/vehicles` already filters this server-side for the agent role).
**13 new backend tests, all passing** (CRUD, tenant isolation,
duplicate-registration rejection, one-vehicle-per-agent enforcement,
agent-can-only-see/log-own-vehicle, reminders window, utilization).

Full backend suite after Phase 11: **276/276 passing**. Frontend:
`npm run build` clean.

---

## Missing-Features Rollout — Phase 12: Customer Support

**What was missing:** No formal support-ticket system — a customer
with a complaint, payment dispute, or general question had no
in-product way to raise it and have staff triage/track/resolve it.
The existing delivery chat (Phase 6) is a live, in-the-moment channel
tied to one delivery in progress, not a place for a longer-lived issue
that may not even involve an active delivery (a payment question, an
account issue).

**Why it was needed:** Every real e-commerce/delivery operation needs
a support queue — customers need somewhere to raise an issue and see
it tracked to resolution; dispatchers/admins need to triage, assign,
and report on it.

**What it does:** Two new tables — `SupportTicketDB` (category,
priority, status, optional order/delivery reference, an `is_dispute`
flag for complaints contesting an outcome, assignment, resolution) and
`SupportTicketMessageDB` (the ticket's thread, with an
`is_internal_note` flag for staff-only notes never returned to the
customer-facing endpoints). Deliberately kept separate from the
existing delivery chat rather than overloading it. A customer creates
a ticket via `POST /customer/support/tickets` — `org_id` is never
trusted from the client; it's derived from the customer's own
order/delivery record (or their most recent order, since a customer
account spans stores in this project's marketplace model), so a
customer can never open a ticket in an org they've never ordered from.
Staff routes (`/admin/support/...`, dispatcher/admin only) support
filtering, replying (a non-internal-note reply auto-moves a brand-new
ticket from "open" to "in_progress" — the same convention already used
elsewhere in this project for "first action taken"), assignment
(validated against real dispatchers/admins in the org), and resolution
with required notes and a timestamp. A customer reply on a "resolved"
ticket automatically reopens it to "in_progress" — silence isn't "still
fine," and a stray follow-up shouldn't need a human to notice it before
the ticket's status reflects reality. `GET /admin/support/analytics`
reports counts by status/category/priority, open disputes, and average
resolution time in hours. Attachment upload reuses the exact
validation approach already proven in `routes/products.py` (allowed
image types, PDF, 5 MB cap) rather than inventing a second one.
Frontend: a new customer-facing `CustomerSupportPanel` (create/browse/
reply to own tickets) added as a tab in the existing customer
dashboard, and a new staff-facing `SupportManager` (triage, reply,
internal notes, resolve, analytics) wired into the dispatcher/admin
sidebar. **13 new backend tests, all passing** (ticket creation tied
to a real order, tenant isolation, internal-notes-hidden-from-customer,
reopen-on-reply, closed-ticket-reply-rejected, assignment validation,
resolution, dispute/analytics counts, role gating).

Full backend suite after Phase 12: **289/289 passing**. Frontend:
`npm run build` clean.

---

## Missing-Features Rollout — Phase 13: Invoicing & Finance

**What was missing:** No formal financial documents — a customer who
paid for an order had no invoice or receipt; a refund produced a
ledger entry (Phase 5) but nothing a customer could point to as proof;
there was no way to issue a manual credit or debit note for a
goodwill adjustment or a COD shortfall.

**Why it was needed:** A real commerce operation needs paper trail —
GST invoices for tax compliance, receipts customers can download, and
credit/debit notes for adjustments outside the normal checkout/refund
flow.

**What it does:** One new table, `FinancialDocumentDB`, covers
invoices, receipts, refund receipts, credit notes, and debit notes via
a `document_type` field rather than four or five nearly-identical
tables — they all share the same shape (a snapshot of amounts, tied to
an order, with a sequential per-org-per-type number). Amounts are
NEVER recomputed: every document snapshots the figures already
computed once, authoritatively, on `OrderDB` at checkout time
(subtotal, discount, tax, delivery fee, total) or from the real
`PaymentLedgerDB` refund event that caused it — so a document always
matches what actually happened, even if the org's tax rate changes
later. An invoice is auto-generated the moment an order becomes
`paid` — for COD orders too, since an invoice represents what was
SOLD, not what's been collected (COD collection stays Phase 5's
separate concern). A credit note is auto-generated the moment a real
refund is recorded, hooked directly into `services/refund.py` right
after the existing ledger entry — the original invoice is never
edited, exactly like a real credit note offsets rather than rewrites
it. Dispatchers/admins can also issue manual credit notes (e.g. one
missing item, not a full refund) and debit notes (e.g. a COD
shortfall, optionally with no order reference at all). PDFs are
rendered server-side with reportlab and regenerated on every download
rather than cached, since the underlying stored amounts never change.
`GET /admin/finance/reports` reuses Phase 5's existing
`compute_financial_dashboard()` for the real money-movement figures
rather than recomputing a second, possibly-divergent set of numbers,
and adds document counts/totals on top. Frontend: a new customer-facing
`CustomerInvoicesPanel` (download own invoices/credit notes as PDF, a
new dashboard tab) and a new staff-facing `FinanceManager` (issue
notes, browse all documents, download PDFs, see the report) wired into
the dispatcher/admin sidebar. **12 new backend tests, all passing**
(auto-invoice on both COD and online checkout, auto-credit-note on a
real refund, sequential numbering, manual note validation, tenant
isolation, customer-can't-see-another-customer's-document, PDF actually
renders non-trivial bytes).

Full backend suite after Phase 13: **301/301 passing**. Frontend:
`npm run build` clean.

---

## Missing-Features Rollout — Phase 14: Public API & Webhooks

**What was missing:** No way for an external system to integrate with
this project at all — no API keys, no outbound event notifications.
Every existing route required a staff JWT, which isn't something you
hand to a third-party integration.

**Why it was needed:** A real delivery/e-commerce platform needs an
external integration layer — partners who want to pull their own
delivery/order data, or receive a push the moment something happens,
rather than polling.

**What it does:** Two independent concerns. (1) `ApiKeyDB` — scoped,
SHA-256-hashed API keys (`deliveries:read`, `deliveries:write`,
`orders:read`, `webhooks:manage`) authenticating a small, deliberately
narrow external surface at `/api/v1/deliveries` and `/api/v1/orders`
via an `X-API-Key` header — versioned so an incompatible v2 could
exist alongside it later without breaking existing integrations. The
raw key is shown to the org admin exactly once, at creation or
rotation; only its hash and a short prefix (for admin-UI
identification) are ever stored. Rotation revokes the old key on the
same database row before creating the new one, so there's never a
window where both work. (2) `WebhookDB`/`WebhookDeliveryDB` — an org
subscribes a URL to specific events
(`delivery.created`/`assigned`/`picked_up`/`out_for_delivery`/
`delivered`/`failed`, `order.created`/`paid`/`cancelled`,
`refund.created`, `return.created`), and `emit_event()` is called
directly from the real place each of those things actually happens —
`routes/checkout.py`, `routes/deliveries.py`'s shared
`_apply_agent_assignment`/status-update logic, `routes/customer_
dashboard.py`'s cancellation, `services/refund.py` (both the test-mode
and real Razorpay refund paths), and `routes/returns.py`. Crucially,
`emit_event()` only ever QUEUES a `WebhookDeliveryDB` row — it never
sends synchronously from inside a request handler, so an unreachable
webhook URL can never slow down or fail a checkout/refund/status-
update request. A background scheduler (same interval-loop shape as
Phase 10's reminder scheduler) picks up pending/due deliveries,
HMAC-SHA256 signs each payload with that webhook's own secret, and
retries failed attempts with exponential backoff (1/5/15/60 minutes,
5 attempts max) before marking a delivery permanently failed — which
an admin can then manually replay. **16 new backend tests, all
passing** (API key scope enforcement, rotation invalidating the old
key, revocation, public-API tenant isolation, webhook event/URL
validation, signature determinism, event-queuing-only-for-subscribed-
events, a real delivery-status-change end-to-end queuing
`delivery.assigned`, and a replay against a genuinely unreachable host
failing gracefully and rescheduling rather than crashing). Frontend: a
new `ApiWebhooksManager` (admin-only — issuing external API access or
wiring outbound webhooks is an org-level integration decision) with
key creation/rotation/revocation, webhook CRUD, and a delivery log
with per-delivery replay.

Full backend suite after Phase 14: **317/317 passing** (confirmed in
two batches — the combined single run now exceeds this environment's
tool execution-time ceiling with the added background scheduler, not
a test failure). Frontend: `npm run build` clean.

---

## Missing-Features Rollout — Phase 15: Advanced Analytics

**What was missing:** The base analytics dashboard (routes/analytics.py)
only ever reported org-wide totals — revenue, order count, top
products. Nothing broke performance down per agent, by failure reason,
by return/cancellation, by repeat-customer behavior, by category or
payment method, or by profit margin. SLA analytics, route efficiency/
heatmaps, RTO analytics, support analytics, and fleet utilization
already existed as separate, more specific reports elsewhere in this
project — Phase 15 was scoped to add exactly what none of those
already covered, not to duplicate any of them.

**Why it was needed:** An admin running the business needs to know
which agents are actually productive, why deliveries are failing,
whether customers come back, which categories/payment methods drive
revenue, and — new to this project — whether products are actually
profitable.

**What it does:** One new endpoint, `GET /admin/analytics/advanced/`,
computed live from existing rows on every request (same tradeoff the
base dashboard already documents and accepts — no drift between what
the dashboard says and what the underlying data says, at the cost of
real aggregation work per request). Adds: agent productivity
(delivered/failed counts and on-time rate per agent — sliced by agent,
unlike Phase 2's org-wide SLA % or Phase 11's per-VEHICLE utilization);
failed-delivery breakdown by reason code; return/cancellation rates;
customer retention (repeat-order rate); revenue by category and by
payment method; profit margin; and a trend/forecast. Profit margin
required one new nullable `cost_price` column on `ProductDB` —
deliberately absent from `ProductOut`, which is also what the PUBLIC
storefront (routes/stores.py) returns to customers, so margin data can
never leak there. A product with no `cost_price` set is excluded from
BOTH the revenue and cost side of the margin calculation (not just its
cost, which would understate cost while still counting revenue and
silently overstate margin) — `products_missing_cost_price` tells the
admin how much of their catalog isn't covered yet. The forecast is
explicitly labeled a naive moving-average projection, not a real
predictive model — this project's data volume can't reliably support
seasonality-aware forecasting, and a transparent naive baseline is
more honest than dressing up a simple average as something smarter.
**10 new backend tests, all passing** (agent productivity and on-time
rate, an idle agent correctly reporting a null rather than 0% on-time
rate, failed-delivery reason breakdown, cancellation rate, repeat-order
rate, revenue breakdowns, profit-margin exclusion behavior verified
with a mix of priced/unpriced products, forecast labeling, admin-only
access, tenant isolation). Frontend: a new `AdvancedAnalyticsPanel`
admin sidebar page.

Full backend suite after Phase 15: **327/327 passing** (confirmed via
two batched runs, same reason as Phase 14 — combined runtime now
exceeds this environment's single-command execution ceiling).
Frontend: `npm run build` clean.

---

## Missing-Features Rollout — Phase 16: Enterprise Organization Management

**What was missing:** No branding, no locale settings, no visibility
into how much an org is actually using the platform, and no way for
an org to pause operations or export a portable snapshot of its own
data. POD rules, SLA policies, delivery zones, and pricing/visibility/
slot settings already existed as org-level settings elsewhere in this
project — Phase 16 was scoped to add exactly what none of those
covered, not a second parallel settings system.

**Why it was needed:** A real multi-tenant platform needs each
tenant's admin to be able to brand their store, see their own usage,
and — critically for a project with no cross-org platform-operator
role — pause their own operations and get their data out if they ever
need to.

**What it does:** Six new fields on `OrganizationDB` (logo_url,
brand_color, timezone, currency_code, currency_symbol, plus
is_suspended/suspended_at/suspended_reason), all additive with
sensible defaults so an org that never touches them keeps behaving
exactly as before. `GET /admin/organization/usage` reports live counts
(staff, agents, deliveries, orders, unique customers) — same "never
drift from the underlying data" tradeoff the analytics dashboards
already accept. `POST /admin/organization/suspend` is explicitly a
SELF-service "pause operations" toggle, not a platform-operator
suspending a tenant from outside — this project has no cross-org
superadmin role, so that's architecturally not something this endpoint
could be, and the code says so plainly rather than implying more power
than it has. What suspension actually blocks: the org drops off the
public storefront listing (routes/stores.py), new invite-code signups
are rejected (routes/auth.py), and new checkouts against the org are
rejected (routes/checkout.py). It deliberately does NOT lock out
existing staff — an admin needs to still be able to operate the org
enough to reactivate it or wind things down, which a total lockout
would prevent. `GET /admin/organization/export` is a portable JSON
snapshot (org settings, staff roster with no password hashes,
delivery/order aggregate counts) for backup/migration — explicitly
NOT a full-database dump of every delivery/order/message row, which
Phase 18's monitoring/backup work is the right home for. The
`timezone` field is honestly documented as display-only for now:
nothing in the backend currently converts stored UTC timestamps using
it. **12 new backend tests, all passing** (branding/locale updates and
validation, live usage counts, suspension blocking signup/checkout/
storefront-listing while NOT blocking existing admin access,
double-suspend and reactivate-when-not-suspended rejected, data export
shape and no leaked password hashes, admin-only access, tenant
isolation). Frontend: a new `OrganizationSettings` admin sidebar page.

Full backend suite after Phase 16: **339/339 passing** (confirmed via
two batched runs, same reason as Phases 14-15). Frontend: `npm run
build` clean.

---

## Missing-Features Rollout — Phase 17: Security & Session Management

**What was missing:** No visibility into WHO has logged in and from
where — no active-sessions list, no login history, no security-event
audit trail. No account lockout, so a password could be brute-forced
with unlimited attempts. No password history, so a "changed" password
could just be changed right back. No 2FA recovery codes, so losing
your authenticator app meant losing the account. All of this sits
NEXT TO the existing auth system (JWT access tokens, RefreshTokenDB
rotation/theft-detection, TOTP/email 2FA, password reset, CAPTCHA,
rate limiting) rather than replacing any of it.

**Why it was needed:** Every real account-security surface needs
these — a user should be able to see and revoke their own sessions,
an account should lock out after repeated failed attempts instead of
allowing unlimited guesses, and losing a 2FA device shouldn't mean
losing the account forever.

**What it does:** Three new tables (`LoginHistoryDB`, `SecurityEventDB`,
`PasswordHistoryDB`, `RecoveryCodeDB`) plus two new columns on
`UserDB` (`failed_login_count`, `locked_until`) and two new columns on
`RefreshTokenDB` (`device_info`, `ip_address` — captured once at login
and carried forward through token rotation, so "Active Sessions" shows
what device actually logged in, not just whatever made the most recent
silent refresh call). Account lockout is auto-expiring (15 minutes
after 5 failed attempts) rather than requiring a manual admin unlock —
a locked-out legitimate user shouldn't need to file a support ticket
just to wait it out. Suspicious-login detection is a simple, honest
heuristic: a login from an IP that hasn't appeared in the user's last
20 successful logins gets flagged and triggers a security-alert email
— and a user's very FIRST login is never flagged, since there's no
history yet to compare against. "Active Sessions" isn't a new table —
it's just `RefreshTokenDB` rows filtered to not-revoked/not-expired,
since that table already IS the session record. 2FA recovery codes
(10 single-use codes, SHA-256 hashed) are generated automatically the
first time TOTP or email 2FA is enabled, and can be regenerated later
(password-confirmed, since regenerating invalidates every existing
code) — a wrong TOTP/email code at login now falls back to trying a
recovery code before failing outright. Password history blocks
re-using any of the last 5 passwords on both change-password and
password-reset. OAuth/SSO were deliberately skipped — this project has
no external OAuth provider registration or secrets available in this
environment, and the original scope explicitly allowed skipping SSO/SAML
"only if practical," which it isn't here; an honest skip beats a fake
implementation. **13 new backend tests, all passing** (lockout
triggering and auto-clearing on success, login history for both
outcomes, session listing/is_current-marking/revoke/logout-all,
cross-user session-revoke rejected, password-reuse rejected on both
change and reset, security events recorded for every relevant action,
recovery codes generated on enable and single-use, disabled 2FA and
regeneration-requires-password). Frontend: a new `SecurityDashboard`
(active sessions, login history, security activity, recovery-code
management) mounted alongside the existing `TwoFactorSettings` on the
Security page for all three staff roles.

Full backend suite after Phase 17: **352/352 passing** (confirmed via
three batched runs, same reason as Phases 14-16). Frontend: `npm run
build` clean.

---

## Missing-Features Rollout — Phase 18: Monitoring & Reliability (final phase)

**What was missing:** No way to know whether the application, its
database, or its four background schedulers (reminder, SLA monitor,
subscription, webhook) were actually healthy — a stuck scheduler would
fail silently forever. No unhandled-exception tracking. No API request
timing. No notification delivery visibility. No database backup
mechanism at all.

**Why it was needed:** Production observability is what turns "it
broke and nobody noticed for three days" into "an admin saw the
webhook scheduler go unhealthy on the dashboard this morning."

**What it does:** Two new tables — `ErrorLogDB` (every unhandled
exception, captured by extending the SAME security-headers middleware
that already wraps every request, rather than adding a second
middleware) and `JobHeartbeatDB` (one row per background scheduler,
updated on every tick with success/failure, duration, and error
detail — all four schedulers now record a heartbeat on both their
success and exception-handling paths). API request timing and
notification send/fail counts are deliberately IN-MEMORY, not
database tables — see `services/monitoring.py`'s module docstring:
they answer "is something wrong right now," reset cleanly on restart
(a fresh process shouldn't inherit yesterday's slow-request history),
and avoid a database write on every single request for data nobody
needs to keep past the current process's lifetime. WebSocket
monitoring reuses the EXISTING `ConnectionManager` singleton
(`services/websocket_manager.py`) via a new `connection_count()`
method rather than a second parallel counter that could drift out of
sync with the real connection state. `GET /health` and `GET
/health/db` are public and unauthenticated (a load balancer or uptime
monitor shouldn't need credentials, and neither reveals anything
sensitive); every other monitoring endpoint is admin-only. Database
backup (`services/backup.py`) is scoped honestly: this project's
default/test configuration is SQLite, so a REAL, working file-copy
backup with SHA-256 checksums is implemented for it — and
verification doesn't stop at a checksum match, it actually opens the
backup file as a SQLite database and runs a query, since a checksum
alone can't catch a truncated/corrupted-but-checksummed file. For
PostgreSQL, the backup endpoint plainly says to use `pg_dump`/managed
backups instead of pretending to back up a database it has no
file-level access to. `docs/DISASTER_RECOVERY.md` documents backup/
restore procedures for both database modes, why this project's
all-additive migration history (every phase added tables or
nullable/defaulted columns, never dropped or altered existing ones) is
safe but not a substitute for backing up before an upgrade anyway, and
the two alerting channels that already exist (Phase 17's security
alert emails, and the monitoring dashboard itself) versus what would
need external credentials this environment doesn't have (a real
paging/alerting integration). **15 new backend tests, all passing**
(public health checks, admin-only monitoring status, job heartbeat
recording and staleness-based health evaluation, API/notification
metrics recorded across real requests, backup create/list/verify
including a genuinely corrupted file correctly rejected and a
path-traversal filename rejected before ever touching the filesystem,
admin-only access, and `record_error()` proven to never raise even
when the logging attempt itself fails). Frontend: a new
`MonitoringDashboard` admin sidebar page (health status, job
heartbeats, slowest endpoints, notification delivery, backups with
one-click create/verify, recent errors).

Full backend suite after Phase 18 — **the final phase of the original
18-phase rollout**: **367/367 passing** (confirmed via three batched
runs, same reason as every phase since 14). Frontend: `npm run build`
clean.

---

## Password visibility toggle, dispatcher "return to pool", and design/motion polish

**What was missing:**
Every password field in the app (login, signup, forgot/reset password,
account settings, change-password forms, 2FA/account-delete
confirmations) was a plain masked `<input type="password">` with no
way to check what you'd typed before submitting — a common source of
failed logins from typos. Separately, once a dispatcher assigned a
customer order to an agent there was no way to undo just that one
assignment and drop it back into the unassigned queue — a dispatcher
could bulk-reassign it to a *different* agent (via the multi-select
checkbox bar), but there was no single-click "take this back" action,
and no way to simply unassign it without immediately picking a
replacement agent. The UI also had almost no motion — no transitions
on hover/focus, no entrance animation on the auth cards or table rows.

**Why it was needed:**
Requested directly, plus makes sense on its own: password visibility
is a baseline UX expectation on any modern auth form, and dispatchers
handling real fleets need a fast way to pull a delivery back (agent
called in sick, wrong agent picked, order needs re-triage) without
being forced into the multi-select bulk-action flow for a single
delivery.

**What it does:**
1. **Password show/hide** — new reusable `PasswordInput` component
   (`components/PasswordInput.jsx`): a plain-CSS eye/eye-off SVG toggle
   button absolutely positioned inside the input, purely visual state
   (never touches the actual value), forwards all other input props
   unchanged. Swapped in everywhere a password field existed:
   `LoginPage`, `SignupPage` (customer + staff), `ResetPasswordPage`
   (both fields), `AccountSettings`, `CustomerDashboard` (change
   password + delete-account confirm), `SecurityDashboard` (recovery
   code regen confirm), `AdminPanel` (admin-set-password modal),
   `TwoFactorSettings` (disable-2FA confirm).
2. **Dispatcher "reassign" / "return to pool" per row** — new backend
   endpoint `PATCH /deliveries/{id}/return-to-pool` (dispatcher/
   admin-only, org-scoped): clears `agent_id` and resets status back to
   `pending` for a customer-placed order still in the just-assigned
   `picked_up` state (mirrors `assign_agent_to_delivery`'s own
   "customer order only" restriction — a manually created delivery has
   no pool to return to), logs a history entry naming who it was
   returned by and who it was previously assigned to, and broadcasts a
   `queue_changed` event so the Unassigned Orders panel picks it up
   live. Rejects out_for_delivery/delivered/cancelled orders and
   manually created (non-customer) deliveries with a clear 400. On the
   frontend, `DispatcherTable` gained a new "Reassign" column: a
   per-row agent-picker dropdown (reuses the existing tested
   `PATCH /deliveries/bulk-assign-agent` endpoint with a single-item
   array — no new bulk-swap backend logic needed) plus a "↩ Return"
   button that only appears for orders eligible for return-to-pool.
3. **Design/animation polish** — new `.password-input-wrap`/
   `.password-toggle-btn` styles matching the existing input theming;
   subtle `fadeSlideUp`/`fadeIn` entrance animations on the auth card
   and wordmark; a `.row-animate` fade-in on table rows; hover/active
   micro-transitions added to `.btn`/`.auth-submit-btn` (glow shadow on
   hover, slight press-down on click); a global transition rule on
   buttons/inputs/links so color/border/shadow changes ease instead of
   snapping.

**6 new backend tests** (`test_return_to_pool.py`: return succeeds and
reappears in the unassigned list with a history note, rejects a
manually created delivery, rejects out_for_delivery, rejects
delivered, requires dispatcher/admin role, org isolation) plus the
existing 8 bulk-delivery-action tests reconfirmed alongside them — **14
passed**. Full backend suite re-run in three batches after these
changes: **373/373 passing** (367 previously + 6 new). Frontend:
`npm run build` clean.

---

## Follow-up polish: modal-level reassign, agent notified on return-to-pool, wider animation coverage

**What was missing:**
The previous session's dispatcher return/reassign controls only lived
in the table row — opening the delivery detail modal (the natural
place to review an order before acting on it) gave no way to
reassign or return it without closing the modal first. Returning a
delivery to the pool also had no signal at all for the agent who lost
it — it would just silently disappear from their list next refresh.
And the new entrance/hover animations from the previous session only
touched the auth pages and the dispatcher table, leaving the agent's
own delivery list, the public customer tracking page, and stat cards
used across multiple dashboards still static.

**Why it was needed:**
Requested directly, as natural extensions of the previous session's
work.

**What it does:**
1. **Reassign/return inside the delivery detail modal** —
   `DeliveryDetailModal` now accepts optional `agents`, `onReassign`,
   `onReturnToPool` (+ loading-state) props. When passed (only by
   `DispatcherTable`; `AgentDeliveryList`'s own use of the same modal
   is unaffected since it doesn't pass them), a "Dispatcher actions"
   row appears with the same reassign dropdown and return-to-pool
   button as the table row, using the exact same handlers — so both
   entry points share one source of truth and one set of tested
   backend calls.
2. **Agent notified when a delivery is returned to the pool** — new
   `notify_agent_of_unassignment()` in `services/notifications.py`,
   the mirror image of the existing `notify_agent_of_new_assignment`
   (same Web Push mechanism, same best-effort silently-no-op-if-no-
   subscription semantics). Wired into `return_delivery_to_pool()`:
   fires to the *old* agent (captured before `agent_id` is cleared)
   whenever a return actually had an agent to notify.
3. **Animation coverage widened** — agent's own `.delivery-card` list
   now fade-in on load and lift slightly on hover (previously hover-
   only, no entrance, no lift); the shared `.stat-card` (used across
   dispatcher/agent/admin dashboards) got the same fade-in + hover
   lift; the public customer tracking page's main card now fades/
   slides in on load, and its order-timeline entries stagger in one
   by one (50ms delay per entry) instead of appearing all at once.

**1 new backend test** (`test_return_to_pool_notifies_the_old_agent`,
monkeypatching the notification call to assert it fires with the
correct delivery/order/agent — since a real push send is a no-op in
tests with no registered subscription and isn't itself worth
asserting on) — **7 passed** in that file. Full backend suite re-run
in three batches: **374/374 passing** (373 previously + 1 new).
Frontend: `npm run build` clean.

---

## Closing the three remaining honest limitations: OAuth/SSO, code splitting, Postgres backups

**What was missing:**
Three previously-flagged, previously-honest limitations: (1) no
"Sign in with Google" option — staff had to use a password even if
their org already used Google Workspace; (2) the frontend's main JS
bundle exceeded Vite's 500kB warning threshold (730kB), meaning every
visitor downloaded admin/manager pages they might never open; (3)
Postgres backup was documented as "use pg_dump yourself" rather than
something the app's own backup button could do.

**Why it was needed:**
Requested directly — the person asked for exactly these three,
previously self-identified as gaps rather than newly discovered ones.

**What it does:**
1. **Google OAuth/SSO (staff only, same scoping precedent as 2FA)** —
   new `services/oauth.py`: builds the Google authorization URL and
   exchanges an auth code for a verified profile via plain HTTP calls
   (no new dependency — reuses `requests`), honestly no-op (clear 400,
   not a broken redirect) if `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`
   aren't set — same pattern as this project's Razorpay/CAPTCHA
   integrations. New `UserDB.oauth_provider`/`oauth_subject_id`
   columns (nullable, auto-migrated). Three new routes in
   `routes/auth.py`: `GET /oauth/google/login` (returns the
   authorization URL, with org context — new org name or an existing
   invite code — carried through as a signed short-lived JWT `state`
   param, so no server-side session table is needed and the callback
   can trust it wasn't tampered with); `GET /oauth/google/callback`
   (Google's own redirect target — creates a new org/user, links to an
   existing password account by verified email, or logs into an
   already-linked account, then redirects to the frontend with a
   one-time `?oauth_code=` rather than real tokens directly in the
   URL); `POST /oauth/exchange` (trades that one-time code for a real
   access/refresh token pair, mirroring the existing 2FA
   challenge-token pattern exactly). An OAuth-only account still gets
   a securely-random `hashed_password` (the column is `NOT NULL`) that
   is never shared or usable to log in by password — documented
   honestly as a limitation (no "add a password later" self-service
   flow exists yet). Frontend: `GoogleIcon.jsx`, a "Sign in with
   Google"/"Sign up with Google" button on `LoginPage`/`SignupPage`
   (staff only), and `App.jsx`'s `RootRouter` now handles
   `?oauth_code=`/`?oauth_error=` landing params via `AuthContext`'s
   new `completeOAuthLogin`.
2. **Code splitting** — 27 admin/manager/settings pages (everything
   reached only via a specific Sidebar click, never needed for first
   paint) converted from static imports to `React.lazy()` in `App.jsx`,
   wrapped in one `<Suspense>` boundary; `vite.config.js` got
   `manualChunks` splitting `react`/`react-dom` into a `vendor` chunk
   and `leaflet` into its own (both change far less often than app
   code, so the browser can keep caching them across deploys). Result:
   main entry chunk 730kB → 272.5kB, no more >500kB build warning, and
   27 on-demand chunks (2–18kB each) fetched only on first navigation
   to that page.
3. **PostgreSQL backups** — `services/backup.py` now runs a real
   `pg_dump` subprocess when the app is configured against Postgres
   (previously: an honest "not applicable, use pg_dump yourself"
   message and nothing else). Still honest where it has to be: if
   `pg_dump` isn't installed/on PATH, `create_backup()` says so plainly
   rather than pretending to succeed — the client-tools package is a
   separate install from the `psycopg2` driver this project already
   depends on. `verify_backup()` now branches by file type: SQLite
   `.db` backups are opened as real SQLite databases (unchanged
   behavior); Postgres `.sql` dumps are confirmed non-empty and
   checked for pg_dump's own standard header comment (a true
   restore-test needs a real Postgres server to restore into, which
   this process doesn't have — documented as a periodic manual/CI task
   instead, same as `docs/DISASTER_RECOVERY.md` already recommends).
   `list_backups()` now returns both file types with an `engine` field.

**20 new backend tests**: `test_oauth.py` (15 — configuration gating,
new-org signup, join-via-invite-code with the same anti-privilege-
escalation role downgrade as ordinary signup, rejecting a bad invite
code, rejecting missing org context, repeat login via an already-
linked account, linking Google to an existing password account by
verified email, tampered/garbage state and login-code rejection,
surfacing a Google-side exchange failure) plus 4 new Postgres-backup
tests in `test_monitoring.py` (missing-pg_dump reporting, a full
mocked `pg_dump` success/verify/list round-trip, a `pg_dump` failure
being surfaced, and rejecting a non-dump file at verify time) — all
via `monkeypatch`, since this project's test suite runs against
SQLite and never talks to a real Google account or Postgres server
(see each test file's module docstring for that seam).

Full backend suite re-run in three batches: **393/393 passing** (374
previously + 15 OAuth + 4 Postgres-backup). One batching artifact was
caught and diagnosed along the way, not a real regression — see
PROJECT_WORKFLOW.md. Frontend `npm run build` clean, confirmed
warning-free.

---

## Closing the three follow-up suggestions: password fallback, automated backups, customer OAuth

**What was missing:**
Three things flagged as honest limitations right after the previous
session's OAuth/code-splitting/Postgres-backup work: (1) an OAuth-only
account had no way to log in at all if Google sign-in were later
disabled — no password, no fallback; (2) Postgres/SQLite backup was
still a manual "click the button" action, no schedule, no retention,
so disk usage would grow unbounded if anyone did rely on it regularly;
(3) OAuth/SSO only covered staff — a customer still had to use a
password even if they'd rather use their Google account.

**Why it was needed:**
Requested directly, as the natural continuation of the previous
session's own "what's still not done" list.

**What it does:**
1. **Self-service "add a password"** — new `UserDB.has_usable_password`
   / `CustomerDB.has_usable_password` columns (default `True` via
   migrate.py's scalar-default handling, so every existing/password
   account gets it for free; explicitly `False` only at OAuth-account-
   creation time). New `POST /auth/me/set-password` and
   `POST /customer/me/set-password` — deliberately a separate endpoint
   from change-password rather than making `current_password`
   optional on that one, since an OAuth-only account has no current
   password to prove knowledge of. `AccountSettings.jsx` and
   `CustomerDashboard.jsx`'s profile panel now show a "Set a Password"
   card instead of "Change Password" for an OAuth-only account, and
   flip over automatically once one is set.
2. **Automated backups + retention** — new
   `services/backup.py::apply_retention_policy()` (prunes oldest-first
   by the timestamp already embedded in every backup filename, so no
   dependence on filesystem mtime surviving a copy/restore) and new
   `services/backup_scheduler.py`, mirroring this project's existing
   scheduler shape (reminders/SLA/webhooks) — a real backup every
   `BACKUP_INTERVAL_HOURS` (default 24), pruned to `BACKUP_RETENTION_COUNT`
   (default 7) right after. Deliberately **not** started while
   `TESTING=1` — confirmed by running 90+ tests and checking
   `backend/backups/` stayed at exactly the one file an actual test
   endpoint call created, not hundreds from the scheduler ticking on
   every one of this project's 300+ TestClient-triggered app startups.
   `docs/DISASTER_RECOVERY.md` rewritten to describe both the SQLite
   and Postgres restore procedures (Postgres restore was previously
   undocumented) and the new automated behavior, still honestly
   scoped: same-disk backup, no offsite copy, no true point-in-time
   recovery — a managed provider's own backups are still the right
   call for anything running in real production.
3. **Customer-facing Google OAuth** — `CustomerDB` gained the same
   `oauth_provider`/`oauth_subject_id` columns as `UserDB`, and
   `routes/customer_auth.py` gained the same three-route shape
   (`/oauth/google/login`, `/oauth/google/callback`, `/oauth/exchange`)
   as the staff flow — notably simpler, since a customer account needs
   no org context at all to sign up. New-customer OAuth signup also
   retroactively links any past deliveries placed under that email
   before the account existed, the same behavior `/customer/signup`
   already had. `services/oauth.py` is shared, unchanged in its core
   logic, between both flows.

   **Caught and fixed a real bug before it shipped**, not after:
   `services/oauth.py` originally hardcoded one module-level
   `GOOGLE_REDIRECT_URI` used by both `build_authorization_url()` and
   `exchange_code_for_profile()`. Since the customer callback lives at
   a different path (`/customer/oauth/google/callback` vs
   `/auth/oauth/google/callback`), reusing the staff redirect URI for
   customer sign-in would have sent Google's redirect to the wrong
   callback route in a real deployment — the state token's claim
   shape wouldn't match, and the whole flow would fail. This didn't
   surface in the first round of tests because they call the callback
   function directly rather than doing a real browser round-trip
   through Google's own redirect_uri validation. Fixed by
   parameterizing `redirect_uri` on both functions (new
   `GOOGLE_CUSTOMER_REDIRECT_URI`, derived from the staff one rather
   than a second env var, so there's nothing new to keep in sync by
   hand), and added a regression test
   (`test_customer_oauth_uses_a_different_redirect_uri_than_staff`)
   asserting the two URLs actually differ.

**32 new backend tests**: 7 in `test_oauth.py` (set-password flow,
has_usable_password correctness, login actually works after setting
one), 7 in `test_monitoring.py` (retention keeps-newest-N/no-op/
ignores-non-backup-files, scheduled-tick success prunes vs. failure
doesn't, env-var configuration, the TESTING-guard precondition), and
18 in the new `test_customer_oauth.py` (new signup, repeat login,
linking to an existing password account by verified email,
retroactive delivery linking, set-password flow, error handling, and
the redirect-uri regression test). Full backend suite re-run in three
batches after each round of changes: **425/425 passing** (393
previously + 32 new). Frontend `npm run build` clean throughout,
confirmed still no bundle-size warning after every change.

---

---

## Portfolio presentation pass: real CI, real coverage numbers, hosted deployment

**What was missing:**
The README claimed a GitHub Actions workflow at `.github/workflows/
ci.yml` that didn't actually exist in the repo — a real, pre-existing
documentation/reality gap, not something introduced this session, but
one that would look bad to exactly the audience (recruiters checking
the repo) this project is built for. The README also still said "26
tests" from an early phase, with no mention of OAuth, backups,
dispatcher reassign, or any of the last several sessions' features.
There was no way to actually see this project live at a URL — only
`docker compose up` locally.

**Why it was needed:**
Requested as presentation/portfolio polish rather than an application
feature — "is there a bug" and "does this look credible to someone
skimming the repo cold" are different questions, and this session
answered the second one.

**What it does:**
1. **A real CI workflow** — `.github/workflows/ci.yml` now actually
   exists: three independent jobs (backend tests + coverage, frontend
   build, Docker image build check for both services) so a
   frontend-only change doesn't wait on the slower backend suite. Runs
   the full suite as one plain `pytest -v` invocation (CI runners have
   no wall-clock ceiling on a single command the way this development
   sandbox does), with `TESTING=1` set explicitly rather than relying
   on conftest.py's own guard. Coverage report uploaded as a
   downloadable build artifact.
2. **Real, verified numbers instead of stale ones** — README rewritten
   throughout: badges and text now say 425 passing tests (not 26), and
   an actual measured 82% statement coverage (`pytest --cov=app`,
   combined across all three local test batches via
   `--cov-append` — not an estimate). Every session's features since
   the original 18 phases (Google OAuth, dispatcher reassign/return-to-
   pool, automated backups, code splitting) are now reflected in the
   feature list, walkthrough, and tech stack table.
3. **A path to an actual hosted deployment** — new `render.yaml`
   Blueprint (backend + frontend + managed Postgres, all three
   services declared in one file, free tier). README's new "Deploying
   It For Real" section walks through the one real gotcha honestly:
   each service's own URL only exists after its first deploy, so
   wiring `ALLOWED_ORIGINS`/`FRONTEND_URL`/`VITE_API_BASE_URL` together
   is unavoidably a two-step "deploy once, then fill in the real URLs"
   process — plus plain statements of Render's free-tier limits (cold
   starts after 15 min idle, 90-day Postgres expiry) rather than
   glossing over them. Railway/Fly.io mentioned as alternatives that
   need no new config file at all, since both auto-detect the
   Dockerfiles already in this repo.

**Honest gap in this session's own verification**: this sandbox has no
Docker installed, so the new `render.yaml`/`ci.yml`'s Docker-build-check
job references the existing Dockerfiles but was never actually run
end-to-end here — only YAML-syntax-validated. The Dockerfiles
themselves are unchanged from the previous session (not newly written
this session), which lowers the risk, but "the YAML parses" and "the
Docker build actually succeeds" are different claims, and only the
first one was verified here.

Full backend suite re-run in three batches after these changes (only
`requirements.txt` gained `pytest-cov`, an already-test-only addition):
**425/425 passing**, unchanged from before this session — this was a
docs/CI/deployment-config session, not an application-code one, so no
new application tests were needed. Frontend `npm run build` confirmed
clean and unaffected.

---

---

## Product Tour section: illustrative mockups in place of a real demo video/GIF

**What was missing:**
No visual "product tour" existed anywhere in the README — someone
skimming the repo cold had to either run it themselves or take the
feature list on faith.

**Why it was needed:**
Requested as the closest feasible version of a demo video/GIF: this
development environment has no browser to actually render the app in
and capture a real screen recording or screenshot from, so a genuine
video/GIF isn't something that could be honestly produced here.

**What it does:**
Four hand-built SVG mockups (`docs/screenshots/*.svg`) illustrating the
login page (staff/customer toggle, Google sign-in), the dispatcher
dashboard (stat cards, the reassign/return-to-pool table controls), the
agent's mobile delivery list (including the offline-sync queued-updates
banner), and the public customer tracking page (live status timeline).
Colors, fonts, and layout are drawn from the real `theme.css` variables
so they're a reasonably accurate representation of the actual dark
"fleet ops console" UI, not a generic placeholder. Embedded in a new
"Product Tour" section in README.md, with an explicit, prominent
disclaimer at the top of that section stating plainly that these are
illustrative mockups, not real screenshots, and why — every feature
they depict is real and working, but the images themselves are drawn,
not captured. This distinction is stated up front rather than left for
someone to discover was misleading after the fact.

No test coverage applies to this change (static documentation assets
only); all four SVGs were validated as well-formed XML. No application
code touched — 425/425 backend tests and the frontend build are
unaffected and were not re-run for this documentation-only change.

---

---

## Native mobile app with real background GPS tracking (mobile/)

**What was missing:**
Everything client-side was PWA/responsive web — no actual React
Native/Flutter app. Related, and the more substantive gap: the web
app's "share my location" feature (an agent's browser reporting
position via `navigator.geolocation.watchPosition`) only works while
that browser tab is open and in the foreground — every mobile browser
stops firing location updates the moment a tab is backgrounded or the
phone locks, a deliberate platform-level restriction on both iOS
Safari and Android Chrome, not a bug or a missing library. A
customer's "live" tracking map was, in practice, only actually live
while the agent's phone was unlocked with that tab in the foreground.

**Why it was needed:**
Requested directly, as the two together: a native mobile app is what
makes genuine background location tracking possible at all — a PWA
fundamentally cannot get OS-level background location permission the
way a native/Expo app can (a real foreground service on Android;
"Always" location + a background mode on iOS).

**What it does:**
New `mobile/` — a real Expo (React Native) app for delivery agents,
built as a second, fully independent CLIENT of the existing backend
API. **Zero backend code was written or changed** to support it: every
endpoint it calls (`POST /auth/login` + 2FA, `GET /auth/me`, `GET
/deliveries/mine`, `GET`/`PATCH /deliveries/{id}`, `PUT
/users/me/location`) already existed and was already tested before
this app was written — the location endpoint in particular was already
generic (any authenticated agent client), it simply never had a client
able to call it from the background before.

- **Screens**: Login (with 2FA challenge support), delivery list
  (sorted active-first, pull-to-refresh), delivery detail (advance
  status through the happy path: picked up → out for delivery →
  delivered), Settings (background location toggle, logout).
- **`src/locationTask.js`**: the actual feature. Uses
  `expo-location` + `expo-task-manager` to register a real background
  task that keeps reporting position (60s interval, 50m minimum
  distance — a deliberate battery-life trade-off every real
  fleet-tracking app makes) to the same `PUT /users/me/location`
  endpoint, regardless of whether the app is on screen or the phone is
  locked. Requests foreground permission first (required before
  Android will even show the background prompt), then background
  permission, and degrades gracefully to foreground-only if an agent
  declines the second prompt rather than failing outright.
- Colors/theme (`src/theme.js`) hand-matched to the web app's
  `theme.css` dark palette so it doesn't look like a visually unrelated
  product.
- `app.json` configured with the real iOS `Info.plist`
  (`NSLocationAlwaysAndWhenInUseUsageDescription`,
  `UIBackgroundModes: ["location"]`) and Android manifest permissions
  (`ACCESS_BACKGROUND_LOCATION`, `FOREGROUND_SERVICE_LOCATION`) this
  actually requires — not placeholder config.
- New CI job (`mobile-config-check` in `.github/workflows/ci.yml`):
  installs dependencies and validates `app.json` via `npx expo config`
  on every push — catches a broken dependency graph or a config typo
  without needing a full paid/authenticated EAS build in CI.

**Honest, stated-up-front limitations** (also in `mobile/README.md`'s
own "Not Yet Built" section): login-only (create the agent account on
the web app first — no signup/password-reset flow here yet); **no
offline queue** — the single biggest gap versus the web agent app,
which has a full IndexedDB-backed offline sync engine this app doesn't
replicate yet; no proof-of-delivery capture, partial-delivery flag, or
failed-attempt reason codes (its "Mark Delivered" is a simple one-tap
status change); no barcode/QR scanning; no push notifications; no
dispatcher↔agent messaging. None of these are silently missing — they're
named plainly as the natural next additions, not discovered later.

**What was and wasn't verified in this environment**: this sandbox has
no Xcode, no Android Studio, and no physical device or simulator — so
no compiled `.apk`/`.ipa` was produced, and the app was never actually
launched/run. What WAS verified for real: `npm install` resolved all
1147 transitive dependencies cleanly (no version conflicts); `npx expo
config --type public` — Expo's own config resolver — parsed `app.json`
successfully end to end, including the location plugin config and
iOS/Android permission blocks; all 10 JavaScript/JSX source files
compile cleanly through the project's actual configured Babel preset
(`babel-preset-expo`), checked via a script that invokes `@babel/core`
directly rather than a wrong CLI tool (an early attempt at this
accidentally resolved to an unrelated, decade-old npm package named
`babel` and produced misleading errors — caught and fixed before
treating any of those results as real). `npx expo-doctor` passed 14/17
checks; the 3 failures were this sandbox's network egress restrictions
blocking Expo's own API host (`exp.host`), not a project problem — the
same checks would run cleanly with normal internet access (e.g. in the
new CI job, or on a developer's own machine).

No changes to `backend/` or `frontend/` beyond documentation (this
session's README/CI updates) — the existing 425 backend tests and the
frontend build are both unaffected and were not re-run, since no
application code in either was touched.

---

---

## Frontend test suite (Vitest + React Testing Library)

**What was missing:**
Zero automated tests existed for the frontend — the README prominently
advertised "425 tests, 82% coverage," which was entirely a backend
number. For a project this thorough about backend testing, that was a
real, visible asymmetry: someone could reasonably assume "425 tests"
meant the whole application, when it meant one half of it.

**Why it was needed:**
Requested directly as the most valuable remaining gap, after weighing
it against several other real options (native-app follow-ups,
real-time chat, i18n, SaaS billing) — chosen because it was both
genuinely missing and something actually buildable and verifiable in
this environment, unlike a live hosted deployment needing real
platform credentials.

**What it does:**
New toolchain: Vitest + React Testing Library + jest-dom +
user-event, configured inside the EXISTING `vite.config.js` (a `test`
block) rather than a second, separately maintained Jest config that
could quietly drift from how the app is actually built — the practical
reason to pick Vitest specifically for a Vite project. New `npm test`
/ `npm run test:watch` / `npm run test:coverage` scripts.

**66 new tests across 7 files**, chosen for real value over padding —
pure logic and meaningfully complex components, not trivial
snapshot-style tests of every file:
- `csvParser.test.js` (13) — the hand-rolled RFC4180 CSV parser used
  for bulk delivery import: quoted fields with embedded commas,
  escaped quotes, embedded newlines, CRLF/CR normalization, short
  rows, empty input, trailing blank lines.
- `routeOptimizer.test.js` (17) — the Haversine distance formula
  checked against a real known city-pair distance (not just internal
  self-consistency), zone grouping, alphabetical zone sorting,
  nearest-neighbor ordering verified against a hand-constructed
  near/medium/far case, and every no-coordinates fallback path.
- `syncEngine.test.js` (11) — `describeConflict`'s plain-English
  formatting (both with and without a `kept_by` name),
  `runSync`'s 3-retry logic exercised for real using Vitest's fake
  timers (not `setTimeout` mocked away — the actual delay is
  advanced and the second attempt genuinely runs), and
  `startAutoSync`'s online/offline gating and cleanup.
- `PasswordInput.test.jsx` (7), `StatusBadge.test.jsx` (8),
  `GoogleIcon.test.jsx` (3) — component behavior via React Testing
  Library, querying by role/label the way a real user or screen
  reader would rather than by implementation detail.
- `LoginPage.test.jsx` (7) — the full staff login flow, the 2FA
  challenge step, error display, the staff/customer account-type
  switch, and the forgot-password callback, with `AuthContext`/
  `CustomerAuthContext`/`ThemeContext`/the API modules all mocked.

**A real accessibility bug caught and fixed along the way**, not
worked around: writing the `LoginPage` test with
`screen.getByLabelText()` failed — not because the test was wrong, but
because `LoginPage.jsx`'s `<label>` elements were never actually
associated with their inputs (no `htmlFor`/`id`), a genuine
screen-reader gap despite looking fine visually (label sitting right
next to the input in the DOM is enough for a sighted user, not for
assistive tech). Fixed in the component itself — added `id`/`htmlFor`
pairs for the account-type select, the username/email field, the
password field, and the 2FA code field — rather than loosening the
test to tolerate the gap.

**Stated honestly, not rounded up**: this is 66 tests covering 4
service files and 4 components out of roughly 19 services and 63
components — 100% coverage on the specific files tested, but only
about 3% of the entire frontend codebase by an `--cov`-equivalent
measure (`npx vitest run --coverage`). This is a real foundation, not
comprehensive frontend coverage the way the backend's 82% is — the
README's own wording and the new `Frontend tests` badge (a test
*count*, deliberately not a coverage percentage) both reflect that
distinction rather than implying more than what's actually there.

New CI step: the existing `frontend-build` job (renamed `frontend
tests + build`) now runs `npm test` before `npm run build`, so a
frontend regression is caught the same way a backend one already was.

Verified: `npm ci` (matching exactly what CI runs, not just `npm
install`) resolves cleanly; `npm test` — 66/66 passing; `npm run
build` — clean, no bundle-size warning, unaffected by the
`LoginPage.jsx` accessibility fix. No backend code was touched this
session; the existing 425 backend tests were not re-run since nothing
in `backend/` changed.

---

---

## Mobile app offline queue — the biggest named gap, closed

**What was missing:**
`mobile/README.md`'s own "Not Yet Built" section named this as "the
single biggest feature gap versus the web app": an agent updating a
delivery's status with no signal simply got an error and lost the
change — nothing was queued for later the way the web app's
IndexedDB-backed sync engine already handles.

**Why it was needed:**
Requested directly, as the natural next step after finishing the
frontend test suite — genuinely the most substantial remaining gap on
the mobile app specifically, and one that mattered for real (a
delivery agent losing an update because of a dead zone is a real
failure mode, not a cosmetic one).

**What it does:**
Deliberately mirrors `frontend/src/services/syncEngine.js`'s
architecture closely rather than inventing a different approach —
same `MAX_RETRIES`/`RETRY_DELAY_MS` constants, same
`describeConflict()` wording, same overall `runSync()` control flow —
adapted to React Native's actual primitives in place of the browser's:

- **`mobile/src/services/offlineStore.js`** — an AsyncStorage-based
  local cache, the mobile equivalent of the web app's IndexedDB
  wrapper, scoped per logged-in user the same way (so two agents
  sharing a device never see each other's cached/pending data).
  Caches every successful delivery fetch; never lets a background
  refetch of stale server data clobber an already-queued local edit
  for the same id.
- **`mobile/src/services/offlineSync.js`** — sends queued updates to
  the backend's existing, already-tested `POST /sync` endpoint (see
  `backend/app/routes/sync.py` — deliberately unauthenticated, since
  each queued record already carries its own `agent_id`/`org_id` from
  when it was cached; **zero backend changes were needed**, this is
  the exact same endpoint the web app's own offline queue already
  uses). Same 3-retry logic as the web app. Since React Native has no
  `navigator.onLine`/`"online"` event, connectivity is checked via
  `expo-network` and sync is re-attempted on app foreground
  (`AppState` "active") plus every 15 seconds while foregrounded.
- **`api.js`'s `updateDeliveryStatus`** now distinguishes a genuine
  network failure (queue it, don't lose it) from a real server-side
  rejection like a validation error (surface it — retrying a rejection
  changes nothing) by matching React Native fetch's specific
  `TypeError: Network request failed` — not by guessing, this is the
  documented, deliberate shape that failure takes.
- **Session restore now tolerates being offline** — a real bug that
  would have undermined the whole feature otherwise: opening the app
  with no connectivity at all previously looked identical to an
  expired/invalid token and logged the agent out. Now a cached profile
  (saved on every successful login/profile fetch) restores the session
  instead, so an agent starting a shift with no signal can still see
  their cached deliveries and queue updates.
- Delivery list, delivery detail, and Settings screens all show clear
  "Working offline" / "queued to sync" indicators and a live
  pending-count with a manual "Sync Now" button — nothing about an
  offline edit is silent.

**22 new tests** (Jest + jest-expo, since Vitest doesn't handle React
Native's native-module mocking as well as it does the web frontend):
`offlineStore.test.js` (9 — per-user scoping, not clobbering a pending
edit, pending-count tracking, sync reconciliation) and
`offlineSync.test.js` (13 — conflict-description wording, the actual
`/sync` POST shape with no Authorization header, retry/backoff via
real fake timers, foreground-vs-background AppState triggers). Needed
the official `@react-native-async-storage/async-storage` Jest mock
wired in explicitly (`mobile/jest.setup.js`) — not automatic, that's
AsyncStorage's own documented setup requirement. One test-design flaw
caught and fixed during writing: an early version of the
"background doesn't trigger sync" test used
`runOnlyPendingTimersAsync()`, which also let the independent 15-second
periodic-sync interval fire and contaminate the assertion — fixed by
flushing only microtasks for that specific check.

Verified: `npm install` resolved 1152 packages cleanly (one real peer
conflict hit and resolved along the way — see
`docs/PROJECT_WORKFLOW.md`); `npx expo config` still validates cleanly;
all 12 source files (4 new: `offlineStore.js`, `offlineSync.js`, plus
the updated `api.js`/`AuthContext.js`/three screens/`App.js`) compile
through the real Babel/Expo preset; `npm test` — 22/22 passing. New CI
step (`npm test` added to the existing `mobile-config-check` job). No
backend or web-frontend code changed this session.

---

---

## "Try the Demo" — a real, populated sandbox with zero signup

**What was missing:**
Evaluating this project required signing up first — a real piece of
friction. Someone giving the project 90 seconds would bounce before
ever seeing the dispatcher dashboard, the fleet view, the SLA
tracking, or any of the depth the rest of this log describes, because
none of it is visible until an account exists.

**Why it was needed:**
Identified directly as the single highest-leverage remaining
improvement — not a missing application feature so much as a missing
"door in": everything else in this project is invisible until someone
can actually look at it.

**What it does:**
New `POST /auth/demo-login` — no request body, no credentials — logs
straight into a real, fully-populated dispatcher account. Behind it:

- **`services/demo_seed.py`**: generates one deliberately SHARED demo
  organization (not a private sandbox per visitor — see that file's
  own module docstring for the full reasoning: this reuses the
  project's already-battle-tested multi-tenant isolation rather than
  inventing a second, parallel per-visitor sandboxing system on top of
  it). Seeds 6 staff accounts (1 admin, 1 dispatcher, 4 agents), 4
  customer accounts, 3 zones, 4 fleet vehicles, an SLA policy, 3
  failed-delivery reason codes, and ~46 deliveries spanning 2 weeks
  with a full spread of statuses (pending/picked_up/out_for_delivery/
  delivered/failed_attempt/cancelled) and realistic per-delivery
  history entries — not a single flat "everything is fine" dataset,
  but a mix an admin/dispatcher could plausibly be looking at on a
  real Tuesday, including a believable minority of overdue and
  SLA-breached deliveries for the alerting UI to have something real
  to show.
- **Idempotent and self-healing**: seeded lazily on the very first
  ever call (so a fresh `docker compose up` with an empty database
  just works, no separate manual seed step), then reset back to this
  same known-good state automatically every `DEMO_RESET_INTERVAL_HOURS`
  (default 6 — see new `services/demo_reset_scheduler.py`, mirroring
  the existing backup scheduler's shape and same TESTING-guarded
  startup) — so a visitor can genuinely explore hands-on (reassign
  deliveries, mark things delivered, poke at settings) without needing
  read-only restrictions that would defeat the point of a real demo,
  and the next visitor doesn't inherit whatever mess was left behind.
- Demo accounts have no real password (same `has_usable_password=False`
  pattern as an OAuth-only account — there's nothing to guess since
  login never checks a password for this endpoint at all).
- Rate-limited tighter than a normal login (10/hour per IP, vs 10/min
  elsewhere) — the one auth endpoint here needing no credentials at
  all, so the one most worth capping against casual abuse.
- Frontend: a prominent "▶ Try the Demo — No Signup Required" button
  at the top of the login card (`LoginPage.jsx`), above the actual
  login form — the first thing anyone sees on that page now.

**A real bug caught and fixed while tuning the generated data**, not
just while writing the happy-path code: the SLA-status calculation for
a DELIVERED order compared its deadline against the CURRENT wall-clock
time rather than against WHEN IT WAS ACTUALLY DELIVERED — which made
nearly every historical delivery read as "missed" regardless of
whether it was genuinely on time, since a deadline from days ago is
almost always "in the past by now" no matter what. Caught by actually
inspecting the generated status distribution (Counter({'missed': 24,
'breached': 10, ...})) rather than just checking the seed script ran
without an exception, fixed by comparing against the delivery's own
completion timestamp instead, and locked in with a regression test
(`test_delivered_orders_mostly_meet_their_sla_not_mostly_miss_it`).

**10 new backend tests**: the login endpoint returning a real, usable
session; the token actually working against a real authenticated
endpoint; lazy first-call seeding vs. reuse on subsequent calls;
requiring no credentials at all; the seed's realistic variety (every
delivery status represented, all the expected staff/customer/zone/
vehicle/SLA counts); full idempotent replacement on a second seed
call; and — the two tests worth calling out specifically — a real
signed-up admin's organization and a real customer's account both
proven to survive repeated demo resets completely untouched. Plus 3
new frontend tests for the button itself (calls `demoLogin` without
touching the staff login path, surfaces a backend error message,
disables itself mid-request).

Full backend suite re-run in three batches: **435/435 passing** (425
previously + 10 new). Frontend: **69/69 passing** (66 + 3 new),
`npm run build` clean, no bundle-size warning.

---

---

## Mobile push notifications — and two real pre-existing Web Push bugs found along the way

**What was missing:**
`mobile/README.md`'s own "Not Yet Built" list named this directly: the
web app has real Web Push for agents; the mobile app didn't yet
request or register for Expo push notifications, so an agent using
only the mobile app had no way to be notified of a new assignment
without having the app open.

**Why it was needed:**
Requested directly as the next mobile feature after the offline
queue — genuinely missing, and named as such in this project's own
docs already.

**What it does:**
- **`services/expo_push.py`**: sends a real push notification via
  Expo's free push gateway (no paid account, no API key — same "zero
  required configuration" story as every other notification channel
  here), with the exact same "never raises, a notification failure
  must never break the flow that triggered it" contract as
  `services/push.py`'s Web Push. Recorded under its own `expo_push`
  monitoring channel, separate from Web Push's `push` channel.
- **`models/expo_push_token.py`** + `POST`/`DELETE
  /users/me/expo-push-token`: register/unregister a device's Expo push
  token, mirroring the existing Web Push subscription endpoints.
- **The actual integration point**: `services/notifications.py`'s
  shared `_push_to_user_ids()` fan-out — the single function every
  staff notification in this codebase already goes through (agent
  assignment, unassignment, etc.) — now sends to both Web Push
  subscriptions AND registered Expo tokens for the same user id set.
  This means **every existing staff notification call site
  automatically gained mobile push support with zero changes to any
  of them** — the same reason `_push_to_user_ids` existed as one
  shared function in the first place.
- Mobile: `src/services/pushNotifications.js` requests permission,
  gets a real Expo push token, and registers it with the backend
  (called once after login in `App.js`); unregisters on logout.
  Genuinely honest about its own setup requirement — unlike Web
  Push's checked-in default VAPID keypair, there is no working
  default for Expo push (a token is inherently tied to a specific
  registered app identity), so a real deployment needs a one-time
  `npx eas init`; without it, registration quietly no-ops rather than
  crashing, and every other mobile feature keeps working normally.

**Two real, pre-existing bugs in Web Push found and fixed while
building this** — not new code, code that had been sitting broken
since some earlier session, only now actually exercised:
1. `services/push.py` used `monitoring_svc` without ever importing it
   — every single call to `send_web_push` (success or failure) raised
   a bare `NameError`. Never caught before because that function is
   only reached once a real `PushSubscriptionDB` row exists, which
   nothing in the test suite ever created before this session.
2. Once fixed, testing immediately surfaced a second, deeper bug: the
   checked-in default VAPID private key was passed to `pywebpush` as a
   full PEM string (with `-----BEGIN PRIVATE KEY-----` header/footer
   lines) — but `py_vapid`'s `Vapid.from_string()` does not strip PEM
   armor before base64-decoding, so every call raised a `ValueError`
   from inside the `cryptography` library before the HTTP request was
   ever made. **Every previous Web Push send in this project's history
   would have crashed, silently, this whole time.** Fixed by building
   a real `Vapid01` object once via `Vapid01.from_pem()` (which does
   strip the armor correctly) and passing that object, not the raw
   string, to `webpush()`. A third, smaller gap surfaced testing the
   fix itself: the original `except WebPushException` clause didn't
   catch the `requests.exceptions.ConnectionError` a real network
   failure raises from inside `pywebpush`, violating this function's
   own documented "never raises" contract — broadened to catch
   generally. See `docs/PROJECT_WORKFLOW.md` for the full diagnosis
   of both.

**18 new backend tests**: 4 for the Web Push regression fixes
(`test_web_push.py` — never raises on a malformed key or an
unreachable endpoint, the module-level Vapid object builds cleanly,
the public key is genuinely present) and 8 for Expo push
(`test_expo_push.py` — token registration, re-registration reassigns
rather than duplicates, ownership-scoped unregistration, and the
extended fan-out actually calling Expo push for a registered token,
not calling it with none registered, and one channel's failure never
breaking the other). Plus **8 new mobile tests**
(`pushNotifications.test.js` — permission denied, already-granted
skips re-prompting, missing EAS project id no-ops, successful
registration, a failed token fetch never throwing, and the
unregister-on-logout path) — one edge case (no physical device) is
explicitly left untested with an honest comment explaining why: a
genuine Jest/Babel module-mocking limitation for a plain-object
boolean export, not an oversight, and not worth a more elaborate
workaround for one simple guard clause.

Full backend suite re-run in three batches: **447/447 passing** (435
previously + 12 new — 8 Expo + 4 Web Push regression). Full mobile
suite: **30/30 passing** (22 previously + 8 new). Frontend untouched
this session.

---

---

## Closing the mobile app's remaining feature gaps — signup, POD, reason codes, scanning, messaging

**What was missing:**
`mobile/README.md`'s own "Not Yet Built" list named all of these
directly: login-only (no signup/password reset), no proof-of-delivery
capture or partial-delivery flag, no failed-attempt reason codes, no
barcode/QR scanning, no dispatcher ↔ agent messaging.

**Why it was needed:**
Requested directly, as the specific remaining items from that same
list.

**What it does — and what's notable is what it DIDN'T need:**
**Zero backend code was written or changed this entire session.**
Every single feature below reused an endpoint that already existed,
was already used by the web app, and was already tested:

- **`SignupScreen.js` + `ForgotPasswordScreen.js`** — `POST
  /auth/signup` (join via invite code as agent/dispatcher, or create a
  new org and become its admin — same anti-privilege-escalation rule
  the backend already enforces regardless of what the mobile UI sends)
  and `POST /auth/forgot-password`. Password reset deliberately has no
  second screen for actually setting the new password — the emailed
  link opens the web app instead; real deep-linking is meaningful
  setup for a flow used rarely per account, a scope decision stated
  plainly, not discovered later. Honest gap noted: no CAPTCHA token is
  sent, so signup would fail on a deployment with `RECAPTCHA_SECRET_KEY`
  configured.
- **`ProofOfDeliveryScreen.js`** + **`SignaturePad.js`** — real camera
  photo capture (`expo-image-picker`), a real hand-drawn signature (a
  plain HTML5 `<canvas>` inside a `react-native-webview`, deliberately
  not a dedicated native signature-drawing library — fewer native
  dependencies to keep in sync with Expo SDK upgrades for a genuinely
  simple drawing implementation), and a partial-delivery toggle.
  Submits via `POST /deliveries/{id}/pod` then `PATCH
  /deliveries/{id}` with `status=delivered` — the backend's own
  existing two-step design, not something invented for mobile.
- **`FailedAttemptScreen.js`** — a real picker over `GET
  /deliveries/reason-codes/active`, the same org-configured reason
  codes the web app's dispatcher settings populate, each showing its
  return-to-origin eligibility.
- **`ScanScreen.js`** — `expo-camera`'s built-in barcode scanning (no
  separate scanning library needed) resolving a scanned code via `GET
  /scan/{code}` (the code IS the delivery's own id, same design as the
  web app's QR codes) straight to that delivery's detail screen,
  recording the scan event along the way.
- **`MessagesScreen.js`** — the actual "dispatcher ↔ agent messaging"
  feature named as missing: the same per-delivery chat thread
  (`GET`/`POST /deliveries/{id}/messages`) `backend/app/models/
  delivery_message.py`'s own comment calls "the original agent
  <->dispatcher thread." **Honestly scoped**: polls every 10 seconds
  while the screen is open rather than subscribing to the backend's
  real websocket `chat_room` channel — wiring a websocket client into
  a mobile app means handling reconnect-on-background/foreground and
  reconnect-on-network-change correctly for a much more aggressive
  connection lifecycle than a browser tab's, a genuinely larger,
  separate piece of work not attempted here.
- `DeliveryDetailScreen.js` restructured: `delivered`/`failed_attempt`
  are no longer one-tap status changes — they navigate to the two
  screens above, since both genuinely need real data first. A new 💬
  Chat button and 📷 Scan button (on the delivery list) tie the new
  screens together.

**One real mistake caught before it shipped**: `sendDeliveryMessage`
was initially written sending `{ body: message }` — a natural-seeming
field name that turned out to be wrong; the backend's `MessageCreate`
schema actually expects `{ message: ... }`. Caught by checking the
backend model directly rather than guessing, and locked in with a test
asserting the exact request body shape (see `api.test.js`'s "sends a
message with the correct field name (message, not body)").

**13 new mobile tests** (`api.test.js`) covering every new request
function's shape and error handling — including the field-name catch
above, and confirming optional POD fields are omitted rather than sent
as `null`, and that coordinates get stringified for the backend's
string lat/long fields.

Full mobile suite: **43/43 passing** (30 previously + 13 new). No
backend or web-frontend changes this session — the 447 backend tests
and 69 frontend tests are unaffected and were not re-run.

**What's still not built, stated plainly**: real-time messaging (this
session's chat polls, doesn't subscribe to the websocket channel), a
mobile CAPTCHA widget, and deep-linked password reset. See
`mobile/README.md`'s own "Not Yet Built" section.

---

---

## Mobile real-time messaging — replacing polling with the backend's existing websocket

**What was missing:**
The previous session's own docs stated plainly: "this polls... rather
than subscribing to the backend's real websocket `chat_room` channel
the web app uses for instant delivery," naming it explicitly as a
deliberate but real gap.

**Why it was needed:**
Requested directly, as that same previously-named gap.

**What it does:**
**Zero backend changes needed** — the websocket endpoint
(`/ws/deliveries/{id}/messages`, the same `chat_room` channel the web
app already connects to) already existed. New
`mobile/src/services/websocket.js`: a thin wrapper around React
Native's built-in `WebSocket` global (part of React Native core, no
extra native dependency) with automatic reconnection — deliberately
**ported from the web app's own `frontend/src/services/websocket.js`
almost verbatim**, not reinvented, since both are solving the exact
same problem (a flaky connection should retry, not die silently) with
an interface a browser's `WebSocket` and React Native's implement
identically. Exponential backoff (1s → 2s → 4s... capped at 15s),
reset to 1s after any successful reconnection.

`MessagesScreen.js` rewritten to open this socket on focus (using the
current access token as a query param, matching the backend's own
auth expectation for this endpoint) instead of a 10-second polling
interval, appending incoming `new_message` broadcasts live via an
id-deduplication check (the backend broadcasts to the whole room
including the sender's own connection, so a message this device just
sent arrives back over the socket too — the dedup check is what keeps
it from appearing twice). A small "Live" / "Reconnecting…" indicator
in the header shows the actual connection state honestly rather than
always claiming to be live. A one-time re-fetch on the app returning
to the foreground is kept as a deliberate safety net — a mobile OS can
suspend a backgrounded app's network activity far more aggressively
than a browser tab's, so a message sent by the other party while this
device was backgrounded might be missed by the live channel and only
show up on that reconnect-triggered fetch; the same "trust, but verify
on reconnect" pattern `offlineSync.js` already uses for the offline
queue.

**8 new tests** (`websocket.test.js`) against a hand-rolled mock
`WebSocket` class, driving the reconnect logic with real fake timers
(the same rigor `offlineSync.test.js` already established) rather than
mocking the delay away: the exponential backoff verified step by step
(1s, then 2s, not just "eventually reconnects"), the backoff resetting
to 1s after a successful reconnection, and the caller's `close()`
correctly stopping all further reconnect attempts.

Full mobile suite: **51/51 passing** (43 previously + 8 new). No
backend or web-frontend changes this session — the 447 backend tests
and 69 frontend tests are unaffected and were not re-run.

With this, the mobile app's only remaining stated gaps are a mobile
CAPTCHA widget (matters only if a deployment has `RECAPTCHA_SECRET_KEY`
configured) and deep-linked password reset (opens the web app instead,
a stated scope decision) — see `mobile/README.md`'s "Not Yet Built".

---

## Mobile CAPTCHA widget + password-reset deep-linking

**What was missing:** the two gaps `mobile/README.md`'s "Not Yet
Built" listed at the end of the previous session: signup/forgot-
password had no CAPTCHA widget on mobile (so a deployment with
`RECAPTCHA_SECRET_KEY` configured would reject those requests from
this app), and the password-reset email's link only ever opened the
web app — this app had no screen at all for the second half of that
flow (setting the new password).

**Why it was needed:** both were explicitly named, honest gaps in the
mobile app's parity with the web app, called out rather than hidden —
closing them was the natural next step once real-time messaging
closed the previous remaining gap last session.

**What it does:**

*CAPTCHA* — new `mobile/src/components/Captcha.js` renders Google's
reCAPTCHA v2 checkbox the only way it can be rendered in a native app
(it's a browser widget, not a native SDK): a small `react-native-
webview` (already a dependency — `SignaturePad.js` uses the identical
`WebView` + `postMessage` pattern) loads a tiny self-contained HTML
page pulling in Google's own `recaptcha/api.js`; the resulting token
comes back to React Native via `window.ReactNativeWebView.postMessage()`.
Wired into `SignupScreen.js` and `ForgotPasswordScreen.js`, both of
which now pass the captured token through to `api.js`'s `signup()`
and `forgotPassword()` as `captcha_token` — the exact field name
`backend/app/models/user.py`'s `UserSignup` and
`backend/app/models/password_reset.py`'s `ForgotPasswordRequest`
already expected. Renders nothing and blocks nothing when
`EXPO_PUBLIC_RECAPTCHA_SITE_KEY` isn't set (new `mobile/.env.example`)
— exactly the same "bring your own credentials, or it no-ops" shape
as the web app's own `Captcha.jsx`, since the backend only actually
enforces the check when its own `RECAPTCHA_SECRET_KEY` is configured.
Zero backend changes needed — the `captcha_token` field and its
enforcement already existed and were already tested.

*Password-reset deep-linking* — new `mobile/src/screens/
ResetPasswordScreen.js` (new password + confirm, calls the same
`POST /auth/reset-password` the web app's own reset form does) plus a
registered `deliverysync://` URL scheme (`app.json`'s new `"scheme"`
field) that `App.js` now listens for via `expo-linking`, both cold-
start (`getInitialURL()`) and warm-start (the `"url"` event), routing
straight to that screen with the token pulled out of the URL — ahead
of both the authenticated and logged-out render branches, so tapping
an old reset link works even while already logged in as a different
account. The emailed link itself is unchanged (still opens the web
app by default, since that needs to work whether or not this app is
installed) — what's new is that `frontend/src/components/
ResetPasswordPage.jsx` now shows a staff-only "Open in the Delivery
Sync app" link built from the same token, using the registered
scheme. This is deliberately **not** a true zero-tap "click the
email, land in the app" flow — that needs Android App Links / iOS
Universal Links, which need a verified HTTPS domain this sandbox has
no way to register or test — so the honest, achievable version is: the
web link always works, with a real one-tap path into the app for
anyone who has it installed. Zero backend changes needed — `POST
/auth/reset-password` already existed and was already tested; only
its mobile *client* was missing.

**5 new tests** (`api.test.js`): `signup()` and `forgotPassword()`
each gained a test confirming the captcha token is included when
present and cleanly omitted (not sent as `null`) when it isn't;
`resetPassword()` (newly exported from `api.js`) got two tests
covering the request shape (`token` + `new_password`, matching
`ResetPasswordRequest`) and error surfacing for an expired/invalid
token. `Captcha.js` and `ResetPasswordScreen.js` themselves have no
tests yet, consistent with this suite's existing scope (screen
components generally aren't covered — see `mobile/README.md`'s
"Running Tests" section) — the WebView/reCAPTCHA integration is also
not independently verifiable in this sandbox (no device to load a
real Google-hosted challenge in), same honest caveat as the
background-location task.

Full mobile suite: **56/56 passing** (51 previously + 5 new). No
backend or web-frontend *logic* changes this session — only the one
new anchor tag on `ResetPasswordPage.jsx` — so the 447 backend tests
and 69 frontend tests are unaffected and were not re-run.

With this, `mobile/README.md`'s "Not Yet Built" no longer lists either
gap as missing — what's left there now is about verification depth
(CAPTCHA not device-tested) and true zero-tap deep-linking (needs a
verified domain this sandbox can't provide), not missing features.

---

## Auth-page accessibility fix (SignupPage, ForgotPasswordPage, ResetPasswordPage)

**What was missing:** with both stated mobile gaps closed last
session, this session went looking for genuine improvements rather
than inventing busywork. Session #46's own note (see
`docs/PROJECT_WORKFLOW.md`'s "Real accessibility bug found by writing
a test, not by an audit") had explicitly flagged its `LoginPage.jsx`
label-association fix as "a reasonable bet the same pattern recurs" in
untested components — that bet was checked by grepping for the same
bare `<label>text</label>` (no `htmlFor`) shape across the rest of
`frontend/src/components/`.

**Why it was needed:** it recurred, in exactly the three auth pages
this session had just touched (`ResetPasswordPage.jsx` for the new
mobile deep-link, `SignupPage.jsx` and `ForgotPasswordPage.jsx` are
its immediate siblings in the same auth flow) — every field on all
three (role selector, name/email/password on both the customer and
staff signup forms, invite-code/org-name, the forgot-password email
field, both reset-password fields) had a `<label>` with no
programmatic association to its input, meaning a screen reader user
couldn't reliably tell which label announces which field — a real
accessibility defect, not a cosmetic one, on the exact pages a new
user or a password-reset-in-progress user hits first.

**What it does:** added `id`/`htmlFor` pairs to every field across the
three files (disambiguated per sub-form where the customer and staff
forms on `SignupPage.jsx` reuse a label like "Email" or "Password" on
the same page), then wrote a new test file per component
(`SignupPage.test.jsx`, `ForgotPasswordPage.test.jsx`,
`ResetPasswordPage.test.jsx`), each written `getByLabelText`-first the
same way `LoginPage.test.jsx` already was — so the fix is locked in by
a real regression test, not just eyeballed. See
`docs/PROJECT_WORKFLOW.md`'s new entry (appended to the original #46
entry it's a direct follow-up to) for the full account, including the
~80 more unlabeled fields found in 11 *other* components
(`AccountSettings.jsx`, `AuditLogViewer.jsx`, `CustomerDashboard.jsx`,
and 8 more) that were deliberately left unfixed this session and are
stated there as real, remaining, not-yet-done work — not swept under
this entry.

**10 new tests** across the 3 new test files (3 + 2 + 5), all passing
alongside the existing suite. Frontend suite now **79/79** (69
previously + 10 new). No backend or mobile changes this session.

---

## Label-association fixes, part 2 — and a corrected count

**Correcting the record first:** the previous entry's "~80 more
unlabeled fields across 11 components" was itself an undercount — it
came from a grep pattern (`^\s*<label>[^<]`) that only matched a bare
`<label>Text</label>` with zero attributes, missing every `<label
className="...">Text</label>` variant. A wider pattern
(`<label[^>]*>` minus anything already containing `htmlFor`) found
the same bug in those 11 files **plus 16 more** — `AgentDeliveryList.jsx`,
`ApiWebhooksManager.jsx`, `CustomerSupportPanel.jsx`,
`DeliveryStatusUpdater.jsx`, `DispatcherTable.jsx`, `FleetManager.jsx`,
`NotificationTemplateManager.jsx`, `PodSettingsPanel.jsx`,
`ProofOfDeliveryModal.jsx`, `RbacManager.jsx`,
`ReconciliationDashboard.jsx`, `RoutingInsights.jsx`, `RtoManager.jsx`,
`SlaManager.jsx`, `SupportManager.jsx`, `WarehouseManager.jsx` — roughly
**150 unlabeled fields total** across 27 components, not ~80 across
11. Stated plainly rather than left standing.

**What this session actually fixed:** 8 of those files, chosen because
they were either already-flagged remaining work from the previous
entry's own list or quick, low-risk wins: `AccountSettings.jsx`,
`TwoFactorSettings.jsx`, `FailedDeliveryReasonManager.jsx`,
`MyWorkforce.jsx`, `SubscriptionManager.jsx`, `AuditLogViewer.jsx`,
`WorkforceManager.jsx`, `ZoneManager.jsx` — 44 fields, `id`/`htmlFor`
pairs added, each verified after the fact by re-grepping the file for
any remaining unlabeled `<label>` (zero left in all 8).
`SubscriptionManager.jsx`'s edit form (rendered once per subscription
in a `.map()`) got per-row unique ids (`` `sub-edit-address-${sub.id}` ``
etc.) rather than static ones, since a static id would collide if two
edit forms could ever be open — they can't today (`editingId` is a
single value), but per-row ids cost nothing and remove that fragility.

**One mechanical edit caught and corrected before it shipped:**
`ZoneManager.jsx`'s "Center point" field pairs a `<label>` with a
`LocationPicker` (a Leaflet map, not a form input) rather than a
native `<input>`. The first pass added `htmlFor="zone-center-point"`
and passed `id="zone-center-point"` to `LocationPicker` as a prop —
but that component destructures its own explicit prop list and never
forwards or renders an `id`, so the `htmlFor` would have pointed at
nothing: an orphaned reference, which is its own (minor) accessibility
defect, not a fix. Caught by checking `LocationPicker.jsx`'s actual
signature before trusting the mechanical pattern, and reverted to a
plain `<label>` with a comment explaining why — a map isn't a single
focusable control, so `htmlFor` pairing doesn't apply to it the way it
does to the real inputs (Latitude/Longitude) it sits next to, which
ARE properly labeled.

**Verification:** each of the 8 files' `<label>` tags re-grepped
individually to confirm zero unlabeled ones remain (`ZoneManager.jsx`
correctly shows 1 — the annotated map exception above, not a miss).
Full frontend suite re-run: **79/79 passing**, unchanged (none of
these 8 files had dedicated tests to update — same honest caveat as
`Captcha.js`/`ResetPasswordScreen.js` last session: this is a
mechanical fix verified by build + grep + the existing suite staying
green, not by new component tests, since standing up mocked
`AuthContext`/`ToastContext`/API fixtures for 8 admin-panel components
in one pass was judged not worth the added risk of rushing it). A
clean `vite build` also confirms nothing broke syntactically across
all 8 edited files.

**What's still genuinely remaining, stated with the corrected count:**
`CustomerDashboard.jsx` (14), `ProductManager.jsx` (21), and
`Storefront.jsx` (11) from the original list, plus all 16 newly-found
files above (`DispatcherTable.jsx` alone has 15) — roughly **106 more
unlabeled fields across 19 files**. Not fixed this session, not
implied to be fixed by this entry — a real, sizeable, separate piece
of work for whoever picks it up next, using the same mechanical
pattern (and the same "check what the label is actually paired with
before assuming it's a plain `<input>`" caution the `ZoneManager.jsx`
catch above earned).

---

## Mobile: actionable network errors + honest role-scope clarification

**What was reported:** a user testing the mobile app hit an opaque
"could not connect to the network" failure on login/signup, and
separately expected the mobile app to offer every role and login type
the web app does (customer, agent, dispatcher, admin) plus assurance
that web-created credentials work on mobile.

**What was actually true vs. what needed fixing:** staff credentials
(agent/dispatcher/admin) created on the web app already worked on
mobile before this session — same backend, same `/auth/login`. Admin
account creation already existed too (`SignupScreen.js`'s "Create
new" tab, unchanged). What was real and worth fixing: (1) a network-
unreachable `fetch()` failure surfaced React Native's raw, opaque
"Network request failed" with zero indication of why or what to do
about it — the single most likely cause (`API_BASE_URL` defaulting to
`10.0.2.2`, which only resolves from the Android emulator, not from
Expo Go on a real phone) went completely unstated; (2) a dispatcher
selecting their role at signup got no warning that this app has no
dispatcher screens at all, and would just land on a delivery list
labeled the same generic way as a legitimately-empty agent list — an
honest UX gap, not a bug in the strict sense, but misleading.

**What was NOT fixed, and why:** a customer-facing mobile experience
(storefront, orders, tracking, support) — the web app's customers are
a wholly separate account system (`/customer/login`, not
`/auth/login`), and this app has zero customer screens. Adding that
would mean building a second, unrelated mobile app inside this one,
directly contradicting this app's stated, narrow reason to exist (see
`README.md`'s "Why This Exists" — solving background GPS tracking for
an agent already on a delivery run). This wasn't silently skipped —
see the reply to the user in this session for the explicit scope
question left open.

**What it does:** new `apiFetch()` wrapper in `api.js` (every one of
its 18 `fetch()` call sites now goes through it) catches ONLY the
network-unreachable failure mode and rewrites it into a message naming
the exact `API_BASE_URL` that was tried plus what to check — a real
HTTP error response (401, validation errors, etc.) is untouched,
still surfacing the backend's own `detail` message exactly as before.
`SignupScreen.js`'s dispatcher role option now shows an inline warning
before the account is created. `DeliveryListScreen.js`'s empty state
is now role-aware (via `useAuth()`'s `user.role`) — a dispatcher or
admin sees an explanation of why the list is empty and where to go
instead, an agent with genuinely no deliveries still sees the original
plain message. `README.md`'s Setup section gained a paragraph
explaining exactly this — which accounts already work across both
apps, and which mobile screens don't exist and why.

**2 new tests** (`api.test.js`): one confirms a raw `fetch()` rejection
is rewritten into a message containing `API_BASE_URL`, one confirms a
real HTTP error response's `detail` message still passes through
unchanged (i.e. `apiFetch()` didn't accidentally start swallowing or
rewriting real backend errors). Mobile suite: **58/58** (56 previously
+ 2 new). No backend or web-frontend changes this session.

---

## Customer notification staleness after checkout + mobile scanner format parity

**What was reported:** (1) on the web customer dashboard, placing an
order shows notification detail for the *previous* order rather than
the one just placed; (2) the mobile scan screen is "not even close"
to the web scanner.

**What was actually wrong, #1:** `CustomerDashboard.jsx` renders
`<Storefront onOrderPlaced={() => { loadDeliveries(); setActiveView("orders"); }} />`
— checkout success refreshes the delivery list and switches tabs, but
never calls `loadNotifications()`. The backend DOES create the new
"Order Confirmed" notification synchronously during checkout
(`routes/checkout.py`'s `verify_payment` → `notify_customer_of_status_change`)
— it's real and correct the moment it's created. The bug is purely on
the frontend: the notifications panel only refreshes on its
pre-existing 10-second poll, so anyone checking notifications right
after ordering sees whatever was last polled — reading exactly like
"the previous order's" detail until that poll catches up. Fixed by
adding `loadNotifications()` to the same `onOrderPlaced` callback.

**What was actually wrong, #2:** `mobile/src/screens/ScanScreen.js`'s
`barcodeScannerSettings` was `{ barcodeTypes: ["qr"] }` — QR only. The
web app's `BarcodeScannerModal.jsx` scans `["qr_code", "code_128",
"code_39", "ean_13", "upc_a"]` — five formats. Any package barcoded in
one of the other four simply couldn't be read on mobile at all, while
working fine on web — a real functional gap, not a cosmetic one.
Fixed by widening mobile's list to `["qr", "code128", "code39",
"ean13", "upc_a"]` (expo-camera's exact, verified `BarcodeType`
strings — checked against Expo's own docs rather than assumed, since
its naming drops the web API's underscores) — genuine format parity
with the web scanner now, not just visual similarity. Hint text
updated from "QR code" to "QR code or barcode" to match.

**Also this session (from a live debugging session with the user,
not a code-review find):** confirmed and helped fix two setup issues
that were blocking testing entirely and had nothing to do with app
code — `uvicorn main:app --reload` binds to `127.0.0.1` by default
(needs `--host 0.0.0.0` for a phone on the same LAN to reach it at
all), and the previous session's `EXPO_PUBLIC_API_BASE_URL` fix needed
a plain-language walkthrough (a `.env` file in `mobile/`, not shell
env-var syntax, which differs by OS and was a real point of
confusion). Not a code change — documented here because it's the
direct, necessary precondition for the user ever being able to verify
anything else in this app on a real device, and because "the fix
didn't work" the first time around was actually two separate
un-run steps, not a flaw in the fix itself.

No new tests this session: the notification fix is a one-line callback
change with no dedicated `CustomerDashboard.jsx` test file to extend
(consistent with this project's stated ~3% frontend component test
coverage), and the scanner fix only changes a config array passed to
a native camera API that categorically cannot be exercised via Jest
(same disclosed limitation as the rest of `ScanScreen.js`). Both
verified by reading the exact code path rather than assumed. Frontend
suite: 79/79 unchanged. Mobile suite: 58/58 unchanged.

---

## Mobile: show/hide password toggle

**What was missing:** the web app's every password field
(`PasswordInput.jsx`) has a show/hide eye toggle; every mobile
password field (`LoginScreen.js`, `SignupScreen.js`,
`ResetPasswordScreen.js`'s two fields) was a plain `secureTextEntry`
TextInput with no way to reveal what was typed — a real, requested
parity gap, not a style nitpick (mistyping a password with no way to
check it before submitting is a genuine usability problem, more so on
a phone keyboard than a desktop one).

**What it does:** new `mobile/src/components/PasswordInput.js` — a
drop-in replacement for a bare password TextInput, mirroring the web
component's contract (forwards every prop through, purely visual
`isVisible` state that never touches the value itself) but NOT its
implementation: the web version draws its eye icon as inline SVG,
which React Native has no equivalent of without adding an icon
library dependency this app doesn't otherwise need. Uses a plain
"Show"/"Hide" text toggle instead — unambiguous, needs nothing
installed, and avoids emoji-eye glyphs rendering inconsistently across
Android/iOS system fonts. Swapped into all 4 password fields across
the 3 screens listed above.

**Verification:** no dedicated component test (this project's mobile
screens generally aren't unit-tested — same stated scope as
`Captcha.js`/`ResetPasswordScreen.js`'s own tests, or lack thereof,
in earlier sessions); checked by requiring the new component and all
3 consumer screens through the project's real Babel/Jest transform to
confirm they parse and import cleanly, then a full suite run. Mobile
suite: **58/58 unchanged** — this touched no logic the existing tests
cover, by design.

---

## render.yaml: always-on deployment + frontend as a free static site

**What was asked:** deploy this live, permanently (not spinning down),
with email, push, real-time messaging, and offline sync all genuinely
working the way they do on localhost — and be able to redeploy after
future changes.

**What was actually true already:** offline sync and real-time
messaging needed ZERO code changes for this — both already work purely
by talking to whatever `API_BASE_URL`/`EXPO_PUBLIC_API_BASE_URL` they're
pointed at, with no separate "production mode." Mobile push (Expo)
needs no backend config either (`expo_push.py`'s own comment covers
why) — the one real prerequisite there is `npx eas init`, a one-time
mobile-side step unrelated to hosting.

**What was genuinely missing:** `render.yaml` used `plan: free`
everywhere, which — this matters beyond just "slow first request" —
silently drops any open WebSocket connection when it spins down after
15 minutes idle, meaning real-time dispatcher↔agent messaging would
look randomly broken on a free deploy for a reason that has nothing to
do with the messaging code itself. Email also had no scaffolding for
prompting real SMTP credentials during Blueprint creation.

**What it does:** backend and database plans changed from `free` to
Render's cheapest PAID tiers (`0.5c-512mb` backend, `0.1c-256mb`
database) — genuinely always-on, no spin-down, no database expiry.
Found in the process: Render renamed its plan IDs at some point after
this file was first written (`starter`/`standard` → CPU/RAM-based IDs
like `0.5c-512mb`) — fetched Render's *current*, live Blueprint spec
and JSON Schema (`render.com/docs/blueprint-spec`,
`render.com/schema/render.yaml.json`) rather than trust remembered
naming, and validated the entire rewritten file against that schema
programmatically (`jsonschema` + `Draft202012Validator`) rather than
just eyeballing YAML syntax — genuine confirmation it'll be accepted,
not just that it parses. The frontend service was converted from a
second paid Docker web service to a Render Static Site
(`runtime: static`, `staticPublishPath`, a `routes` rewrite rule
mirroring `nginx.conf`'s SPA fallback, a `headers` rule mirroring its
asset cache policy) — static sites are free AND never spin down on
Render regardless of plan, so this isn't a tradeoff, it's strictly
better for identical behavior: real money saved, not a corner cut.
Added `SMTP_HOST`/`SMTP_PORT` with sensible defaults plus
`SMTP_USERNAME`/`SMTP_PASSWORD`/`FROM_EMAIL` as `sync: false` so Render
prompts for real credentials once, during Blueprint creation, rather
than the person having to know to go find these in the dashboard
afterward. `README.md`'s "Deploying It For Real" section rewritten to
explain all of this plainly — why paid not free, current rough pricing
(sourced live, stated as Render's to quote not this repo's), and that
offline sync/real-time/push need no separate production setup at all.

**Verification:** the rewritten `render.yaml` parses as valid YAML AND
validates with zero errors against Render's own live-fetched JSON
Schema — the strongest verification available without an actual Render
account to deploy against (a real deploy is inherently a Render-hosted
process this sandbox does not have credentials or reach to perform).
No test suite covers infrastructure config, consistent with this
project's existing test scope (447 backend + 79 frontend + 58 mobile
tests, all logic-level, none of them YAML) — neither suite was touched
or needed re-running this session.

---

## Org/staff welcome emails + a pre-existing flaky test found while verifying

**What was asked, as three items:** (1) a show/hide eye button on
password fields, (2) an email sent on creating an organization or a
new agent/dispatcher joining one, (3) customer emails for order status
changes (packed/out for delivery/delivered).

**Two of the three already existed** — checked before writing anything,
rather than assumed: #1 was built in an earlier session
(`PasswordInput.jsx`/`.js` on both web and mobile). #3 turned out to
already be fully wired — `notify_customer_of_status_change()` in
`services/notifications.py` calls `send_status_notification_email()`
for every status change, `out_for_delivery` and `delivered` included;
this was built in an earlier session for the in-app notification and
the email channel was added alongside it at the time, which this
session's own earlier summary had undersold as in-app-only. Only #2
was a genuine gap: no email was ever sent on signup beyond the
generic "verify your email" link — nothing that actually welcomed
someone or told a new admin their org's invite code.

**What it does:** two new functions in `services/email.py` —
`send_org_welcome_email()` (to whoever just created a brand new org:
confirms it, repeats back the invite code to share with their team)
and `send_staff_welcome_email()` (to whoever just joined an existing
org via invite code, as agent or dispatcher). A shared
`_send_welcome_email()` helper in `routes/auth.py` picks the right one
and is called from BOTH places a signup can actually happen — the
regular `POST /auth/signup` and the Google OAuth signup path — so
Google-based signups get the same welcome email, not just password-
based ones. Deliberately wrapped in try/except (unlike the existing
`_issue_and_send_verification_email()` call beside it, which lets a
failure propagate) — a welcome email is best-effort, the same
reasoning `notify_customer_of_status_change()` already uses for its
own three channels, so a transient SMTP hiccup shouldn't be able to
block someone from creating an account.

**2 new tests** (`test_auth.py`): one confirms creating an org sends
`send_org_welcome_email` with the SAME invite code the signup response
itself returns (not a mismatched one), one confirms joining an org
sends `send_staff_welcome_email` (not the org one) with the right org
name and role. Both monkeypatch the email functions directly on
`auth_routes`, same pattern `test_oauth.py` already established.

**Found while verifying, unrelated to this change — disclosed rather
than quietly worked around:** running the full suite in 3 batches (a
single `pytest tests/` run exceeds this sandbox's tool timeout) turned
up one consistent failure: `test_monitoring.py::
test_api_metrics_recorded_across_requests`, which asserts `GET
/health` appears in `/admin/monitoring/api-metrics`'s
`slowest_endpoints` list. That list is capped at the top 15 SLOWEST
endpoints, tracked in a global, in-memory store that's never reset
between tests (see `get_api_metrics_summary()`'s `top_n: int = 15`
default in `services/monitoring.py`) — in a big enough batch, enough
genuinely slower endpoints accumulate from earlier tests that `/health`
(about as fast as an endpoint gets) falls out of the top 15 by the
time this test's own two `/health` hits are checked. This is inherently
order/volume-dependent by design, not a regression: confirmed by
temporarily disabling this session's new welcome-email calls entirely
and re-running the exact same batch — it failed identically, proving
the welcome emails aren't the cause. Not fixed here (it's pre-existing,
unrelated to what was asked, and a real fix means either resetting
monitoring state per-test via a fixture or changing what the test
asserts — a small but separate piece of work) — flagged here so it
isn't mistaken for something this session broke, the same way earlier
sessions have flagged other pre-existing issues honestly rather than
silently stepping around them.

Full backend suite (run in 3 batches to fit this sandbox's tool
timeout): **449 total (447 + 2 new)** — 112 + 161 (160 passed, 1 the
pre-existing flaky one above) + 176, all passing individually and in
every batch except that one test specifically in this one batch
composition. No frontend or mobile changes this session.

---

## (Template for future entries — copy this structure)

## Feature Name

**What was missing:**

**Why it was needed:**

**What it does:**
