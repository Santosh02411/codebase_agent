/**
 * Real background GPS tracking — this is the actual reason this app
 * exists rather than just using the web app on a phone's browser.
 *
 * The web app (frontend/src/components/AgentDeliveryList.jsx) already
 * has a "Share my location" toggle that calls the exact same PUT
 * /users/me/location endpoint this file calls, via the browser's
 * navigator.geolocation.watchPosition. That works fine — WHILE the
 * browser tab is open and in the foreground. The moment the phone's
 * screen locks, or the agent switches to their maps app for
 * directions, or the browser itself gets backgrounded by the OS to
 * save battery, watchPosition silently stops firing. There is no
 * browser API that reliably keeps GPS updates flowing once the tab
 * itself is backgrounded — this is a deliberate, platform-level
 * restriction on every mobile browser (Safari and Chrome both do
 * this), not a bug or a missing library. A customer's "live" tracking
 * map on the web app is, in practice, only actually live while the
 * agent's phone is unlocked with that tab in the foreground.
 *
 * Expo's TaskManager + Location APIs used below run this task in a
 * real OS-level background service (a foreground service notification
 * on Android — see app.json's isAndroidForegroundServiceEnabled;
 * "Always" location permission + UIBackgroundModes: ["location"] on
 * iOS — see app.json's Info.plist entries) that keeps reporting
 * position updates on the configured interval regardless of what's on
 * screen or whether the screen is even on. This is the genuine,
 * substantive capability gap a native/Expo app closes that a PWA
 * cannot, no matter how the web app's manifest or service worker is
 * configured.
 *
 * Honest limits, stated plainly:
 * - Requires the agent to grant "Always" / "Allow all the time"
 *   location permission, which both iOS and Android now gate behind an
 *   extra confirmation step specifically because of how much battery
 *   and privacy-sensitive background location tracking implies — some
 *   agents will decline it, and the app must (and does, see
 *   startBackgroundLocationTracking's return value) work fine without
 *   it, just falling back to foreground-only updates.
 * - Expo Go (the quick-start testing app) does NOT support background
 *   location on iOS at all as of Expo SDK 51 — a real EAS build
 *   (`eas build`) is required to test/ship this specific feature on
 *   iOS. Android background location works in Expo Go for
 *   development. See mobile/README.md for the full picture.
 * - This reports position on an interval (LOCATION_UPDATE_INTERVAL_MS
 *   below), not continuously — a genuine trade-off against battery
 *   life that every real fleet-tracking app makes the same way.
 */

import * as Location from "expo-location";
import * as TaskManager from "expo-task-manager";
import { pushMyLocation } from "./services/api";

export const LOCATION_TASK_NAME = "delivery-sync-background-location";

// How often the OS wakes this task up to report a position, while the
// app is backgrounded. 60s balances "the tracking map feels live
// enough" against "doesn't drain the agent's battery over an 8-hour
// shift" — every real delivery-fleet app (the ones this project is
// modeled on) makes a similar trade-off, not continuous streaming.
const LOCATION_UPDATE_INTERVAL_MS = 60 * 1000;
const LOCATION_UPDATE_DISTANCE_METERS = 50;

TaskManager.defineTask(LOCATION_TASK_NAME, async ({ data, error }) => {
  if (error) {
    console.error("Background location task error:", error.message);
    return;
  }
  if (!data) return;

  const { locations } = data;
  const latest = locations && locations[locations.length - 1];
  if (!latest) return;

  try {
    await pushMyLocation(latest.coords.latitude, latest.coords.longitude);
  } catch (err) {
    // Best-effort, same as the web app's own location-sharing toggle —
    // a single failed ping (e.g. a dead zone with no signal) shouldn't
    // crash a background task that needs to keep running for the rest
    // of the shift. The next interval's attempt will simply try again.
    console.warn("Background location push failed:", err.message);
  }
});

/**
 * Call this once the agent turns on location sharing (see
 * SettingsScreen.js). Requests foreground permission first (required
 * before Android will even show the background permission prompt),
 * then background permission, then starts the task. Returns
 * { granted: "background" | "foreground" | "denied" } so the calling
 * screen can show an accurate status rather than assuming success.
 */
export async function startBackgroundLocationTracking() {
  const foreground = await Location.requestForegroundPermissionsAsync();
  if (foreground.status !== "granted") {
    return { granted: "denied" };
  }

  const background = await Location.requestBackgroundPermissionsAsync();
  if (background.status !== "granted") {
    // Foreground-only is still useful — the web app's own toggle has
    // never had anything better than this, so this is strictly an
    // improvement (working while the app is open) even without the
    // background upgrade the agent chose not to grant.
    return { granted: "foreground" };
  }

  const alreadyStarted = await Location.hasStartedLocationUpdatesAsync(LOCATION_TASK_NAME);
  if (!alreadyStarted) {
    await Location.startLocationUpdatesAsync(LOCATION_TASK_NAME, {
      accuracy: Location.Accuracy.Balanced,
      timeInterval: LOCATION_UPDATE_INTERVAL_MS,
      distanceInterval: LOCATION_UPDATE_DISTANCE_METERS,
      showsBackgroundLocationIndicator: true,
      foregroundService: {
        notificationTitle: "Delivery Sync",
        notificationBody: "Sharing your location with dispatch while you have an active delivery.",
      },
    });
  }

  return { granted: "background" };
}

export async function stopBackgroundLocationTracking() {
  const started = await Location.hasStartedLocationUpdatesAsync(LOCATION_TASK_NAME);
  if (started) {
    await Location.stopLocationUpdatesAsync(LOCATION_TASK_NAME);
  }
}

export async function isBackgroundLocationTrackingActive() {
  return Location.hasStartedLocationUpdatesAsync(LOCATION_TASK_NAME);
}
