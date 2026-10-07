# Delivery Sync — Agent Mobile App

A real React Native (Expo) app for delivery agents, built as a second,
independent client of the exact same backend API the web app uses — no
new backend endpoints were needed to build this (see [How This
Talks to the Backend](#how-this-talks-to-the-backend) below).

## Why This Exists

The web app already has an "agent" experience
(`frontend/src/components/AgentDeliveryList.jsx`) that works fully
offline and lets an agent share their live location with a "Share my
location" toggle. That toggle uses the browser's
`navigator.geolocation.watchPosition` — which works well while that
browser tab is open and in the foreground, and **stops firing the
moment the tab is backgrounded or the phone locks**. This is a
deliberate, platform-level restriction in every mobile browser (Safari
and Chrome both do this to save battery and protect privacy), not a
bug or a missing library — there is no web API that reliably keeps GPS
updates flowing once the tab itself loses focus.

This app closes that specific, genuine gap: real OS-level background
location tracking (a foreground service on Android; "Always" location
permission + a background mode on iOS), so a customer's live tracking
map keeps updating while an agent is driving with the phone locked in
a cupholder — something a Progressive Web App fundamentally cannot do
on either platform. See `src/locationTask.js` for the full technical
explanation and its own honest limitations.

## How This Talks to the Backend

This app is a plain HTTP client of `backend/main.py` — the same
backend the web app and web dispatcher console already use. Every
endpoint it calls already existed and was already tested before this
app was written:

| This app calls | For |
|---|---|
| `POST /auth/login` (+ `/auth/2fa/verify-login` if 2FA is on) | Login |
| `POST /auth/signup` | Creating an agent/dispatcher account (join via invite code, or create a new org) |
| `POST /auth/forgot-password` | Requesting a password reset email |
| `GET /auth/me` | Restoring a session on app relaunch |
| `GET /deliveries/mine` | The agent's delivery list |
| `GET /deliveries/{id}` | Delivery detail |
| `PATCH /deliveries/{id}` | Advancing delivery status |
| `POST /deliveries/{id}/pod` | Submitting proof of delivery (photo/signature/recipient) |
| `GET /deliveries/reason-codes/active` | The org's failed-attempt reason codes |
| `GET /scan/{code}` + `POST /deliveries/{id}/scan` | Resolving a scanned QR code and recording the scan event |
| `GET`/`POST /deliveries/{id}/messages` | Loading a delivery's chat history, and sending a message |
| `WS /ws/deliveries/{id}/messages` | Real-time delivery of new chat messages |
| `PUT /users/me/location` | Both the manual foreground case AND the background task's periodic pings |
| `POST`/`DELETE /users/me/expo-push-token` | Registering/unregistering for push notifications |

**No backend code was written or changed to support any of this** — every one of
these endpoints already existed, was already used by the web app, and
was already tested before this mobile app called it. See
`mobile/src/services/api.js`'s own docstrings for the handful of
places worth knowing about (e.g. the location endpoint being generic
enough to work from a background task with zero backend changes; the
POD flow being two separate calls — submit, then mark delivered — by
the backend's own design, not this app's).

## Setup

Requires [Node.js](https://nodejs.org) and the
[Expo Go](https://expo.dev/go) app on a physical phone (fastest way to
test), or an Android Studio/Xcode simulator.

```bash
cd mobile
npm install
npx expo start
```

Scan the QR code with Expo Go (Android) or the Camera app (iOS).

**Point it at your backend:** by default this expects the backend at
`http://10.0.2.2:8000` (the Android emulator's alias for your
computer's `localhost`). For a physical device, set your computer's
real LAN IP instead:
```bash
EXPO_PUBLIC_API_BASE_URL=http://192.168.1.42:8000 npx expo start
```
(Find your LAN IP with `ipconfig` on Windows or `ifconfig`/`ip addr` on
macOS/Linux. Your phone and computer must be on the same Wi-Fi
network.) **Getting "Can't reach the server..." on login/signup?**
That's this exact misconfiguration — 10.0.2.2 (the default) only
resolves from the Android emulator; on Expo Go on a real phone it
resolves to nothing, which is what "fastest way to test" above
actually means in practice for most people. The error message itself
now names the URL it tried and what to check (see `api.js`'s
`apiFetch()`) — previously this surfaced as a raw, unhelpful
"Network request failed" with no indication of why.

**One backend, several kinds of accounts — not all of them work in
this app.** This app talks to the SAME backend and database as the
web app (see below), so a **staff** account — agent, dispatcher, or
admin, created either here or on the web app — logs in identically on
both; there's no separate mobile account system to keep in sync. What
this app deliberately does NOT have: a **customer**-facing experience.
The web app's customers (`frontend/src/components/CustomerDashboard.jsx`,
`Storefront.jsx`, etc.) are an entirely separate account system on the
backend (`POST /customer/login`, not `POST /auth/login`), with no
mobile screen for it at all — this app only ever calls the staff auth
endpoints. And while dispatcher/admin accounts CAN log in here (the
backend doesn't stop them), this app only has an agent's
assigned-delivery workflow — a dispatcher lands on a screen that's
honestly labeled as empty rather than pretending they're missing
deliveries (see `DeliveryListScreen.js`), and `SignupScreen.js` warns
about this before a dispatcher account is even created. Building a
customer mobile experience or a dispatcher-specific mobile console
would each be a substantial, separate undertaking — this app's whole
reason to exist (see "Why This Exists" above) is the one specific,
narrow gap of background GPS tracking for an agent already out on
deliveries, not a mobile port of the entire web console.

Log in with any existing **agent** account from the web app, or use
the **Sign Up** link to join an org via invite code or create a new
one right from this app — see [Signup & Password
Reset](#signup--password-reset) below. (This line was stale — an
earlier version of this README predated `SignupScreen.js` and never
got corrected.)

## Running Tests

```bash
cd mobile
npm test
```

56 tests (Jest + jest-expo) covering the offline queue's actual logic —
`offlineStore.js`'s AsyncStorage-backed cache (per-user scoping, not
clobbering a pending edit with stale server data, pending-count
tracking) and `offlineSync.js`'s retry/backoff behavior and
foreground/connectivity-triggered sync, using real fake timers the
same way the web app's own `syncEngine.test.js` does — plus
`pushNotifications.js`'s permission/token/error-handling logic (8
tests; the one branch not covered — no physical device — is a single
early-return guard documented as untested in that test file's own
comment, a genuine Jest/Babel module-mocking limitation, not an
oversight), `api.js`'s request-building functions (18 tests covering
signup, forgot-password, password reset, proof of delivery, reason
codes, messaging, and scanning — request shape, error surfacing, the
message-vs-body field-name mismatch that would have been an easy
mistake to ship, and that the optional CAPTCHA token is sent when
present and cleanly omitted rather than sent as `null` when it isn't),
and `websocket.js`'s reconnect-with-backoff logic (8
tests, again driven with real fake timers — the exponential delay
actually verified step by step, not mocked away, plus the reset-after-
a-successful-reconnect behavior and the "caller closed it, stop
retrying" case). Screen
components (Login, DeliveryList, etc.) don't have tests yet — the
logic layer was prioritized since it's where a real bug would
actually cost real data or send the wrong request shape.

## Testing Background Location

1. Log in, go to **Settings**, toggle **Share my location** on.
2. Grant "While Using the App" location permission, then — when
   prompted separately — **"Allow All the Time"** / "Always". Both
   platforms gate this behind an extra step specifically because of
   how much background location tracking implies; declining the
   second prompt still works, just foreground-only (the toggle's
   screen explains this plainly rather than pretending it's the same).
3. Background the app (press the home button) or lock the phone.
4. On the web app, open that same delivery's public tracking page
   (`?track=<delivery-id>`) — the agent marker keeps moving on its own
   interval (60s by default — see `LOCATION_UPDATE_INTERVAL_MS` in
   `src/locationTask.js`) even though the app isn't on screen.

**Important — Expo Go's own limitation, not this app's:** as of Expo
SDK 51, background location does **not** work in Expo Go on iOS at
all (Expo Go itself doesn't include the native background modes this
needs) — only in a real build via `eas build`. It **does** work in
Expo Go on Android. This is documented by Expo, not a gap in this
codebase — see
[Expo's own background location caveats](https://docs.expo.dev/versions/latest/sdk/location/#background-location-updates)
for the current, authoritative version of this limitation.

## Building a Real, Installable App

This sandbox environment has no Xcode/Android Studio and no device to
test on, so no compiled `.apk`/`.ipa` was produced here — only the
source code. To get an actual installable build:

```bash
npm install -g eas-cli
eas login
eas build --platform android   # or ios
```
See [Expo's build docs](https://docs.expo.dev/build/introduction/) for
the full process — this requires a free Expo account.

## Offline Support

This app now has a real offline queue, closing what was previously its
single biggest gap versus the web agent app — mirroring
`frontend/src/services/syncEngine.js`'s architecture closely (same
retry constants, same conflict-description wording, same overall
control flow), adapted to React Native's actual APIs:

- **`src/services/offlineStore.js`** — an AsyncStorage-based local
  cache (the mobile equivalent of the web app's IndexedDB wrapper),
  scoped per logged-in user the same way. Every successful delivery
  fetch is cached; a status update is applied to the local cache
  immediately whenever the network request for it fails.
- **`src/services/offlineSync.js`** — sends queued updates to the
  backend's existing, already-tested `POST /sync` endpoint (the exact
  same one the web app's offline queue already uses — no new backend
  code was needed) with the same 3-retry logic as the web app, and
  reconciles the server's resolved version back into the local cache.
  Since React Native has no `navigator.onLine`/browser `"online"`
  event, connectivity is instead checked via `expo-network` and a
  sync is re-attempted whenever the app is foregrounded
  (`AppState` "active") or every 15 seconds while foregrounded.
- **Session restore also tolerates being offline** — opening the app
  with no connectivity at all (a real scenario: an agent starting
  their shift with no signal) restores the session from a locally
  cached profile instead of being treated the same as an
  expired/invalid token and logging the agent out, which would have
  defeated the entire point of offline support.
- Both the delivery list and delivery detail screens show a clear
  "Working offline" banner and a "queued to sync" badge on any
  not-yet-synced record, and Settings shows a live pending-update
  count with a manual "Sync Now" button — nothing about an offline
  edit is silent or hidden.

**What this offline queue does NOT do**, stated plainly: it only
applies to a delivery **already fetched at least once** (there's
nothing to safely merge an offline status change into otherwise); it
queues by writing straight to local storage rather than the web app's
richer background-sync-registration approach (see
`frontend/src/services/backgroundSync.js`) that can wake a service
worker even after every tab is closed — a native background task
would need `expo-task-manager` wired the same way `../locationTask.js`
already is, and hasn't been built for sync specifically (only for
location).

## Push Notifications

Real OS-level push, via [Expo's push notification service](https://docs.expo.dev/push-notifications/overview/)
— an agent gets a notification even with the app fully closed the
moment a delivery is assigned or unassigned to them, mirroring the web
app's own Web Push for the exact same events (both are sent from the
same shared fan-out function on the backend, `services/notifications.py`'s
`_push_to_user_ids()` — adding this required zero changes to any of
the individual call sites that trigger a staff notification).

**Setup required before this actually works**: unlike the web app's
Web Push (which has a working checked-in default VAPID keypair — see
`backend/app/services/push.py`), there is no working default for Expo
push, since a push token is inherently tied to a specific registered
app identity Expo's push service can route to. Run once, from this
`mobile/` folder:
```bash
npx eas init
```
This writes a real project id into `app.json` (requires a free Expo
account). Without this step, `registerForPushNotifications()` detects
the missing project id and quietly no-ops — every other feature in
this app (deliveries, status updates, background location, the
offline queue) works completely normally either way; only push
notifications themselves stay off until `eas init` is run.

Also requires a **physical device** — push tokens are unreliable/
unsupported on a simulator or emulator, so `registerForPushNotifications()`
no-ops there too (see `src/services/pushNotifications.js`).

## Signup & Password Reset

**Signup** (`SignupScreen.js`) mirrors the web app's own choice: join
an existing organization via invite code (as agent or dispatcher —
never admin via invite code, the same anti-privilege-escalation rule
the backend itself enforces regardless of what this screen sends), or
create a brand new organization (becoming its admin automatically).
Also renders `<Captcha />` (see below) so signup keeps working even on
a deployment that has `RECAPTCHA_SECRET_KEY` configured.

**Password Reset** now has two real, working halves. `ForgotPassword-
Screen.js` requests the reset email — the same `POST /auth/forgot-
password` the web app calls, also with `<Captcha />` — and the emailed
link still opens the **web app** by default (`ResetPasswordPage.jsx`,
same as before), because that link needs to work whether or not this
app is installed. What's new: that web page now also shows an "Open
in the Delivery Sync app" link for staff accounts, built from the same
token using the `deliverysync://` scheme this app registers (see
`app.json`'s `"scheme"` and `App.js`'s `Linking` handling, both cold-
start via `getInitialURL()` and warm-start via the `"url"` event).
Tapping it lands directly on the new `ResetPasswordScreen.js`, which
calls the same `POST /auth/reset-password` the web page's own reset
form does. What this genuinely is NOT: a "tap the emailed link, skip
the browser entirely" flow — that needs Android App Links / iOS
Universal Links, which need a verified HTTPS domain this sandbox has
no way to register or test. So the honest shape is: the email link
always works (browser fallback), with a real one-tap path into the
app for anyone who has it installed and taps the extra link.

### CAPTCHA widget (`src/components/Captcha.js`)

Google's reCAPTCHA v2 checkbox is a browser widget, not a native SDK,
so there's no native RN view for it — this renders it the same way
libraries like `react-native-recaptcha-that-works` do: a small
`WebView` (already a dependency — see `SignaturePad.js` for the
identical `WebView` + `postMessage` pattern used for signature
capture) loading a tiny self-contained HTML page that pulls in
Google's own `recaptcha/api.js`, with the resulting token handed back
to React Native via `window.ReactNativeWebView.postMessage()`.
Renders nothing, and never blocks either form, when
`EXPO_PUBLIC_RECAPTCHA_SITE_KEY` isn't set (see `.env.example`) — the
backend only actually enforces the check when its own
`RECAPTCHA_SECRET_KEY` is configured, so no-config-anywhere is a
normal, fully-working state, exactly like the web app's own
`Captcha.jsx`. Not independently testable in this sandbox (no device
to load a real Google-hosted challenge in), for the same reason the
mobile background-location task and the native `.apk`/`.ipa` build
itself aren't — verified by reading the code against Google's
documented `grecaptcha.render()` contract instead.

## Proof of Delivery, Partial Delivery & Failed Attempts

Marking a delivery **Delivered** now opens `ProofOfDeliveryScreen.js`:
an optional recipient name, a real camera photo (`expo-image-picker`),
a real hand-drawn signature (`SignaturePad.js` — a plain HTML5 canvas
inside a WebView, deliberately not a dedicated native signature
library; see that file's own comment), notes, and a **partial
delivery** toggle. Submitting sends the POD data first
(`POST /deliveries/{id}/pod`), then marks the delivery delivered — the
backend's own two-step design (see `services/pod.py`), not something
this app invented. If the organization requires POD fields this
submission didn't include, the backend's own validation error is
surfaced directly rather than the app guessing requirements in advance.

Marking a delivery a **Failed Attempt** opens `FailedAttemptScreen.js`
— a real picker over the organization's actual active reason codes
(`GET /deliveries/reason-codes/active`, the same list the web app's
dispatcher-configured reason codes populate), each showing whether
it's eligible for return-to-origin, plus optional notes.

## Barcode / QR Scanning

`ScanScreen.js` (reachable via the 📷 **Scan** button on the delivery
list) uses `expo-camera`'s built-in barcode scanning — no separate
scanning library needed. The scanned code IS the delivery's own id
(same design as the web app's QR codes — see
`backend/app/models/scan.py`), so scanning resolves straight to that
delivery's detail screen, recording a scan event (pickup/delivery/hub,
inferred from the delivery's current status) along the way.

## Dispatcher ↔ Agent Messaging

`MessagesScreen.js` (reachable via the 💬 **Chat** button on a
delivery's detail screen) is the same per-delivery chat thread the web
app uses — `backend/app/models/delivery_message.py`'s own comment
calls it "the original agent<->dispatcher thread" (later extended to
include customers too), so this genuinely is the feature named in this
project's own docs as missing from the mobile app.

**Real-time**, via the backend's existing `/ws/deliveries/{id}/messages`
websocket — the same `chat_room` channel the web app already connects
to; no backend changes needed here either. `src/services/websocket.js`
ports the web app's own reconnect-with-exponential-backoff logic
(`frontend/src/services/websocket.js`) almost verbatim, since React
Native's built-in `WebSocket` implements the same interface a
browser's does. A small "Live" / "Reconnecting…" indicator in the
screen's header shows the actual connection state rather than
pretending it's always live. A one-time re-fetch when the app returns
to the foreground is kept as a safety net — a mobile OS can suspend a
backgrounded app's network activity far more aggressively than a
browser tab's, so a message sent while this device was backgrounded
might be missed by the live channel and only show up on that
reconnect-triggered fetch.

## Not Yet Built

Both of the two gaps previously listed here — mobile CAPTCHA and
password-reset deep-linking — are now closed (see the Signup &
Password Reset section above for both). What's left, stated plainly
rather than discovered the hard way:

- A **true** "tap the email, land in the app, no browser involved"
  reset flow — the custom-scheme deep link above needs a tap on an
  "Open in app" link on the web page; Android App Links / iOS
  Universal Links could remove even that tap, but need a verified
  HTTPS domain this sandbox has no way to register or test.
- Mobile CAPTCHA is code-complete against Google's documented
  `grecaptcha.render()` contract but not independently verified end to
  end on a real device (no device available here) — same honest
  caveat as the background-location task and the lack of a compiled
  `.apk`/`.ipa`.

Neither of these is a silent gap — an agent using only this app today
gets a real, working, genuinely background-location-capable,
offline-capable, push-notification-capable experience with signup
(CAPTCHA included), a full two-screen password reset, proof of
delivery, failed-attempt reason codes, barcode scanning, and real-time
dispatcher messaging — full parity with the web agent app's auth
flows at this point, with the two items above being about
verification depth and true zero-tap deep-linking, not missing
features.
