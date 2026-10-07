/**
 * Tests services/websocket.js against a hand-rolled mock WebSocket
 * class (React Native's global `WebSocket` isn't present in Jest's
 * node test environment) that mirrors the real interface closely
 * enough to exercise the reconnect-with-backoff logic for real: each
 * instance is tracked so a test can manually trigger onopen/onmessage/
 * onclose and assert what connectWebSocket did in response, the same
 * way offlineSync.test.js drives its retry logic with real fake
 * timers rather than mocking away the delay itself.
 */

jest.mock("../api", () => ({ API_BASE_URL: "http://10.0.2.2:8000" }));

class MockWebSocket {
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    MockWebSocket.instances.push(this);
  }
  close() {
    this.readyState = 3;
    if (this.onclose) this.onclose();
  }
  // Test helpers — not part of the real WebSocket interface.
  _triggerOpen() {
    this.readyState = 1;
    if (this.onopen) this.onopen();
  }
  _triggerMessage(data) {
    if (this.onmessage) this.onmessage({ data: JSON.stringify(data) });
  }
  _triggerClose() {
    this.readyState = 3;
    if (this.onclose) this.onclose();
  }
}
MockWebSocket.instances = [];

global.WebSocket = MockWebSocket;

import { connectWebSocket } from "../websocket";

beforeEach(() => {
  MockWebSocket.instances = [];
});

describe("connectWebSocket", () => {
  it("derives a ws:// URL from the http API base URL", () => {
    connectWebSocket("/ws/deliveries/d1/messages?token=abc");
    expect(MockWebSocket.instances[0].url).toBe("ws://10.0.2.2:8000/ws/deliveries/d1/messages?token=abc");
  });

  it("calls onOpen when the socket connects", () => {
    const onOpen = jest.fn();
    connectWebSocket("/ws/x", { onOpen });
    MockWebSocket.instances[0]._triggerOpen();
    expect(onOpen).toHaveBeenCalled();
  });

  it("parses and delivers a JSON message via onMessage", () => {
    const onMessage = jest.fn();
    connectWebSocket("/ws/x", { onMessage });
    MockWebSocket.instances[0]._triggerMessage({ event: "new_message", message: { id: "m1", message: "hi" } });
    expect(onMessage).toHaveBeenCalledWith({ event: "new_message", message: { id: "m1", message: "hi" } });
  });

  it("does not throw and does not call onMessage for malformed JSON", () => {
    const onMessage = jest.fn();
    connectWebSocket("/ws/x", { onMessage });
    const socket = MockWebSocket.instances[0];
    expect(() => socket.onmessage({ data: "not valid json{{{" })).not.toThrow();
    expect(onMessage).not.toHaveBeenCalled();
  });

  it("calls onClose when the connection drops", () => {
    const onClose = jest.fn();
    connectWebSocket("/ws/x", { onClose });
    MockWebSocket.instances[0]._triggerClose();
    expect(onClose).toHaveBeenCalled();
  });

  it("reconnects with exponential backoff after an unexpected close", async () => {
    jest.useFakeTimers();
    connectWebSocket("/ws/x");
    expect(MockWebSocket.instances).toHaveLength(1);

    MockWebSocket.instances[0]._triggerClose();
    expect(MockWebSocket.instances).toHaveLength(1); // not yet — waiting on the 1s backoff

    await jest.advanceTimersByTimeAsync(1000);
    expect(MockWebSocket.instances).toHaveLength(2); // first reconnect attempt

    MockWebSocket.instances[1]._triggerClose();
    await jest.advanceTimersByTimeAsync(1000);
    expect(MockWebSocket.instances).toHaveLength(2); // backoff doubled to 2s — 1s alone isn't enough yet

    await jest.advanceTimersByTimeAsync(1000);
    expect(MockWebSocket.instances).toHaveLength(3); // now at 2s total, second reconnect fires

    jest.useRealTimers();
  });

  it("resets the backoff delay after a successful reconnection", async () => {
    jest.useFakeTimers();
    connectWebSocket("/ws/x");

    // Two failures in a row without ever reopening — backoff climbs to 4s.
    MockWebSocket.instances[0]._triggerClose();
    await jest.advanceTimersByTimeAsync(1000);
    MockWebSocket.instances[1]._triggerClose();
    await jest.advanceTimersByTimeAsync(2000);
    expect(MockWebSocket.instances).toHaveLength(3);

    // This one succeeds — should reset the delay back to 1s.
    MockWebSocket.instances[2]._triggerOpen();
    MockWebSocket.instances[2]._triggerClose();
    await jest.advanceTimersByTimeAsync(1000);
    expect(MockWebSocket.instances).toHaveLength(4); // reconnected after only 1s, not 4s

    jest.useRealTimers();
  });

  it("does not reconnect after close() is called by the caller", async () => {
    jest.useFakeTimers();
    const handle = connectWebSocket("/ws/x");
    handle.close();

    await jest.advanceTimersByTimeAsync(20000);
    expect(MockWebSocket.instances).toHaveLength(1); // no reconnect attempts at all

    jest.useRealTimers();
  });
});
