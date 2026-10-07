/**
 * Tests services/pushNotifications.js's registration logic — the
 * parts that don't require a real physical device or a real Expo
 * project id. Mocks expo-notifications/expo-device/expo-constants and
 * the API layer, same approach as offlineSync.test.js.
 */

jest.mock("expo-device", () => ({ isDevice: true }));
jest.mock("expo-notifications", () => ({
  setNotificationHandler: jest.fn(),
  getPermissionsAsync: jest.fn(),
  requestPermissionsAsync: jest.fn(),
  setNotificationChannelAsync: jest.fn(),
  getExpoPushTokenAsync: jest.fn(),
  AndroidImportance: { HIGH: 4 },
}));
jest.mock("expo-constants", () => ({ expoConfig: { extra: { eas: { projectId: "test-project-id" } } } }));
jest.mock("../api", () => ({
  registerExpoPushToken: jest.fn(),
  unregisterExpoPushToken: jest.fn(),
}));

import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import Constants from "expo-constants";
import { registerExpoPushToken, unregisterExpoPushToken } from "../api";
import { registerForPushNotifications, unregisterCurrentDeviceFromPushNotifications } from "../pushNotifications";

beforeEach(() => {
  jest.clearAllMocks();
  Device.isDevice = true;
  Constants.expoConfig = { extra: { eas: { projectId: "test-project-id" } } };
});

describe("registerForPushNotifications", () => {
  // Note: "not a physical device" (Device.isDevice === false) is a
  // single early-return guard in the source, straightforward to
  // verify by inspection, but not covered by a test here — mutating
  // `Device.isDevice` after this file's top-of-file `import * as
  // Device from "expo-device"` doesn't propagate to the separate copy
  // pushNotifications.js already imported (Babel's CJS interop for
  // `import * as X` takes an independent snapshot of a plain mock
  // object's properties rather than a live binding), and the
  // `jest.isolateModules` + fresh `require()` workaround that
  // normally sidesteps this ran into a second-order issue: the
  // freshly re-required module also gets brand-new, unconfigured
  // copies of every OTHER mocked dependency, so the fresh call fails
  // for an unrelated reason before ever reaching the isDevice check.
  // Not worth a more elaborate workaround for one simple guard clause.

  it("returns null when permission is denied", async () => {
    Notifications.getPermissionsAsync.mockResolvedValue({ status: "denied" });
    Notifications.requestPermissionsAsync.mockResolvedValue({ status: "denied" });

    const result = await registerForPushNotifications();
    expect(result).toBeNull();
    expect(registerExpoPushToken).not.toHaveBeenCalled();
  });

  it("does not re-prompt when permission was already granted", async () => {
    Notifications.getPermissionsAsync.mockResolvedValue({ status: "granted" });
    Notifications.getExpoPushTokenAsync.mockResolvedValue({ data: "ExponentPushToken[abc]" });

    await registerForPushNotifications();

    expect(Notifications.requestPermissionsAsync).not.toHaveBeenCalled();
  });

  it("returns null and never calls the API when no EAS project id is configured", async () => {
    Constants.expoConfig = { extra: {} };
    Notifications.getPermissionsAsync.mockResolvedValue({ status: "granted" });

    const result = await registerForPushNotifications();
    expect(result).toBeNull();
    expect(registerExpoPushToken).not.toHaveBeenCalled();
  });

  it("registers the real token with the backend on success", async () => {
    Notifications.getPermissionsAsync.mockResolvedValue({ status: "granted" });
    Notifications.getExpoPushTokenAsync.mockResolvedValue({ data: "ExponentPushToken[abc]" });

    const result = await registerForPushNotifications();

    expect(result).toBe("ExponentPushToken[abc]");
    expect(registerExpoPushToken).toHaveBeenCalledWith("ExponentPushToken[abc]");
  });

  it("returns null (never throws) if getExpoPushTokenAsync itself fails", async () => {
    Notifications.getPermissionsAsync.mockResolvedValue({ status: "granted" });
    Notifications.getExpoPushTokenAsync.mockRejectedValue(new Error("boom"));

    const result = await registerForPushNotifications();
    expect(result).toBeNull();
  });
});

describe("unregisterCurrentDeviceFromPushNotifications", () => {
  it("calls the API to unregister when permission was granted", async () => {
    Notifications.getPermissionsAsync.mockResolvedValue({ status: "granted" });
    Notifications.getExpoPushTokenAsync.mockResolvedValue({ data: "ExponentPushToken[abc]" });

    await unregisterCurrentDeviceFromPushNotifications();

    expect(unregisterExpoPushToken).toHaveBeenCalledWith("ExponentPushToken[abc]");
  });

  it("does nothing when permission was never granted (nothing to unregister)", async () => {
    Notifications.getPermissionsAsync.mockResolvedValue({ status: "denied" });

    await unregisterCurrentDeviceFromPushNotifications();

    expect(unregisterExpoPushToken).not.toHaveBeenCalled();
  });

  it("never throws even if the API call fails", async () => {
    Notifications.getPermissionsAsync.mockResolvedValue({ status: "granted" });
    Notifications.getExpoPushTokenAsync.mockResolvedValue({ data: "ExponentPushToken[abc]" });
    unregisterExpoPushToken.mockRejectedValue(new Error("network down"));

    await expect(unregisterCurrentDeviceFromPushNotifications()).resolves.toBeUndefined();
  });
});
