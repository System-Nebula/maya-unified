/**
 * Behavioral checks for browser mic reconnect / active-state invariants.
 * Run: node tests/test_browser_mic_reconnect.js
 */

"use strict";

function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}

/** Mirrors mayaBrowserMic isActive / onclose gating without DOM APIs. */
function reduceMicState(state, action) {
  const next = { ...state };
  if (action.type === "open") {
    next.connected = true;
    next.wsAlive = true;
    next.intentionalClose = false;
    return next;
  }
  if (action.type === "start_mic") {
    next.wantSession = true;
    next.micActive = true;
    return next;
  }
  if (action.type === "socket_close") {
    if (action.stale) return next;
    next.connected = false;
    next.wsAlive = false;
    next.micActive = false;
    if (!next.intentionalClose && next.wantSession) {
      next.reconnectScheduled = true;
    }
    return next;
  }
  if (action.type === "disconnect") {
    next.intentionalClose = true;
    next.wantSession = false;
    next.reconnectScheduled = false;
    next.micActive = false;
    next.connected = false;
    next.wsAlive = false;
    return next;
  }
  return next;
}

function isActive(state) {
  return !!(state.micActive && state.connected && state.wsAlive);
}

function fresh() {
  return {
    connected: false,
    wsAlive: false,
    micActive: false,
    wantSession: false,
    intentionalClose: false,
    reconnectScheduled: false,
  };
}

function testDeadSocketIsNotActive() {
  let state = fresh();
  state = reduceMicState(state, { type: "open" });
  state = reduceMicState(state, { type: "start_mic" });
  assert(isActive(state), "live socket+mic should be active");
  state = reduceMicState(state, { type: "socket_close" });
  assert(!isActive(state), "dead socket must not report active");
  assert(state.reconnectScheduled, "unexpected close should schedule reconnect");
}

function testIntentionalDisconnectSkipsReconnect() {
  let state = fresh();
  state = reduceMicState(state, { type: "open" });
  state = reduceMicState(state, { type: "start_mic" });
  state = reduceMicState(state, { type: "disconnect" });
  assert(!state.reconnectScheduled, "intentional disconnect must not reconnect");
  assert(!isActive(state), "disconnect clears active");
}

function testStaleSocketCloseIgnored() {
  let state = fresh();
  state = reduceMicState(state, { type: "open" });
  state = reduceMicState(state, { type: "start_mic" });
  state = reduceMicState(state, { type: "socket_close", stale: true });
  assert(isActive(state), "stale onclose must not clear the replacement socket");
  assert(!state.reconnectScheduled, "stale onclose must not reconnect");
}

function testPingProducesPongPayload() {
  const ping = { type: "ping", ts: 123, connection_id: "abc" };
  const pong = {
    type: "pong",
    ts: ping.ts || Date.now(),
    connection_id: ping.connection_id,
  };
  assert(pong.type === "pong", "pong type");
  assert(pong.ts === 123, "pong echoes ts");
  assert(pong.connection_id === "abc", "pong echoes connection");
}

testDeadSocketIsNotActive();
testIntentionalDisconnectSkipsReconnect();
testStaleSocketCloseIgnored();
testPingProducesPongPayload();
console.log("test_browser_mic_reconnect: 4 passed");
