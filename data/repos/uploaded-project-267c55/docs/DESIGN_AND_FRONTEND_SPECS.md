# Design & Frontend Specs

## 1. Views

### 1.1 Agent View
- List of assigned deliveries (order ID, current status)
- Tap a delivery → choose new status from: Picked Up, Out for Delivery,
  Delivered, Failed Attempt
- Optional notes field for context (e.g. "customer not available")
- Visual indicator per record: "Saved locally" vs "Synced" (small icon/badge)
- A banner at the top showing connectivity state: Online / Offline

### 1.2 Dispatcher Dashboard
- Table of all deliveries: Order ID, Agent, Status, Last Updated, Sync State
- Filter by status (e.g. show only "Failed Attempt" deliveries)
- Manual refresh button to re-fetch latest data

## 2. Interaction Flow (Agent)
1. Agent opens app (works with or without internet)
2. Agent selects a delivery, updates status
3. Update is saved instantly to IndexedDB, UI reflects "Saved locally"
4. App periodically checks connectivity in the background
5. When online, pending records sync automatically; badge updates to "Synced"

## 3. Visual Style
- Keep it minimal and functional — this is a utility tool, not a
  consumer-facing product; clarity over decoration
- Large, easily tappable buttons for status changes (agents often use this
  one-handed, possibly on a phone browser)
- Clear color coding: e.g. green = delivered, yellow = pending sync, red =
  failed attempt

## 4. Components (React)
- `AgentDeliveryList`
- `DeliveryStatusUpdater`
- `ConnectivityBanner`
- `DispatcherTable`
- `SyncStatusBadge`

## 5. Not Included in v1
- Mobile app (native) — this is a responsive web app only
- Offline map or location picker — a simple text field for location notes
  instead
