// jest-expo's own preset handles most React Native module mocking
// automatically, but AsyncStorage needs its official mock wired in
// explicitly (this is AsyncStorage's own documented setup step, not
// jest-expo's job) — without it, any test importing a module that
// touches AsyncStorage fails immediately with "NativeModule:
// AsyncStorage is null", since there's no real native module to back
// it in a Node test environment.
jest.mock("@react-native-async-storage/async-storage", () =>
  require("@react-native-async-storage/async-storage/jest/async-storage-mock")
);
