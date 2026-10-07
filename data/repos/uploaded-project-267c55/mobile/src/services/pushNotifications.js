/**
 * Registers this device for real push notifications and hands the
 * resulting Expo push token to the backend (POST /users/me/expo-
 * push-token — see that route's own docstring). Mirrors the web app's
 * own push-subscription flow (frontend/src/services/pushUtil.js)
 * exactly in spirit — request permission, get a token/subscription
 * from the platform, send it to the backend — just via Expo's
 * push-token API instead of the browser's PushManager.
 *
 * Honest limitation, stated plainly rather than discovered the hard
 * way: getting a real Expo push token requires this app to be linked
 * to a real Expo/EAS project (`npx eas init`, run once, which writes a
 * real project id into app.json) — there is no working default the
 * way services/push.py's checked-in VAPID keypair is a working
 * default for the web app, since a push token is inherently tied to a
 * specific registered app identity Expo's push service can route to.
 * Without that one-time `eas init` step, registerForPushNotifications
 * below detects the missing project id and returns null rather than
 * crashing — the rest of the app (delivery list, status updates,
 * background location, the offline queue) works completely normally
 * either way; only push notifications themselves stay off until that
 * step is done. See mobile/README.md's "Push Notifications" section.
 */

import * as Notifications from "expo-notifications";
import * as Device from "expo-device";
import Constants from "expo-constants";
import { Platform } from "react-native";
import { registerExpoPushToken, unregisterExpoPushToken } from "./api";

// Controls how a notification that arrives while the app is in the
// FOREGROUND is presented — without this handler, Expo's default is
// to not show anything at all while the app is open, which would make
// it look like notifications silently stopped working the moment you
// opened the app to check.
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

/**
 * Call once after login (see App.js). Requests permission, gets a
 * real Expo push token, and registers it with the backend. Returns
 * the token on success, or null if permission was denied, this isn't
 * a physical device (push tokens are unreliable/unsupported on
 * simulators), or this app has no real Expo project id configured yet
 * (see this file's own module docstring) — every case is a quiet,
 * non-fatal no-op, never a crash.
 */
export async function registerForPushNotifications() {
  if (!Device.isDevice) {
    console.log("Push notifications require a physical device — skipping on simulator/emulator.");
    return null;
  }

  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  let finalStatus = existingStatus;
  if (existingStatus !== "granted") {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }
  if (finalStatus !== "granted") {
    console.log("Push notification permission was not granted.");
    return null;
  }

  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("default", {
      name: "Delivery updates",
      importance: Notifications.AndroidImportance.HIGH,
      vibrationPattern: [0, 250, 250, 250],
      lightColor: "#f2a93b",
    });
  }

  const projectId = Constants.expoConfig?.extra?.eas?.projectId;
  if (!projectId) {
    console.log(
      "No EAS project id configured (run `npx eas init` once) — push notifications are unavailable until then."
    );
    return null;
  }

  try {
    const { data: token } = await Notifications.getExpoPushTokenAsync({ projectId });
    await registerExpoPushToken(token);
    return token;
  } catch (err) {
    console.warn("Failed to register for push notifications:", err.message);
    return null;
  }
}

/**
 * Call on logout (see AuthContext.js) — tells the backend to stop
 * sending push to this device, since it's no longer signed in as
 * whichever agent it belonged to.
 */
export async function unregisterCurrentDeviceFromPushNotifications() {
  try {
    const { status } = await Notifications.getPermissionsAsync();
    if (status !== "granted") return;
    const projectId = Constants.expoConfig?.extra?.eas?.projectId;
    if (!projectId) return;
    const { data: token } = await Notifications.getExpoPushTokenAsync({ projectId });
    await unregisterExpoPushToken(token);
  } catch (err) {
    // Best-effort — same "never let a notification-plumbing failure
    // break the actual user-facing action" contract as the backend
    // side of this feature (see services/expo_push.py).
    console.warn("Failed to unregister push token on logout:", err.message);
  }
}
