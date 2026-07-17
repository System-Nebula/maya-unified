/** Execute the shipped browser mic module against a deterministic WebSocket shim. */
"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 3;
  static instances = [];
  constructor(url) {
    this.url = url;
    this.readyState = FakeWebSocket.CONNECTING;
    this.bufferedAmount = 0;
    this.sent = [];
    this.onopen = null;
    this.onmessage = null;
    this.onerror = null;
    this.onclose = null;
    FakeWebSocket.instances.push(this);
  }
  send(payload) { this.sent.push(payload); }
  open() {
    this.readyState = FakeWebSocket.OPEN;
    if (this.onopen) this.onopen();
  }
  message(payload) {
    if (this.onmessage) this.onmessage({ data: JSON.stringify(payload) });
  }
  close() {
    if (this.readyState === FakeWebSocket.CLOSED) return;
    this.readyState = FakeWebSocket.CLOSED;
    if (this.onclose) this.onclose();
  }
}

class FakeAudioContext {
  constructor() {
    this.state = "running";
    this.sampleRate = 48000;
    this.audioWorklet = { addModule: async () => {} };
    this.destination = {};
  }
  async resume() {}
}

const syncedSessions = [];
const endedSessions = [];
const playbackEvents = [];
let leader = true;
const audio = {
  syncSession: (sessionId) => syncedSessions.push(sessionId),
  endSession: (sessionId) => endedSessions.push(sessionId),
  handleEvent: (event) => playbackEvents.push(event),
  activeSessionId: () => syncedSessions.at(-1) || null,
  activeGeneration: () => 7,
  activeTurnId: () => "turn-7",
  isSpeaking: () => false,
  onSpeakingChange: () => () => {},
};
const windowObject = {
  mayaBrowserAudioOutput: audio,
  mayaVoiceLeader: { isLeader: () => leader },
  addEventListener() {},
};
const sandbox = {
  window: windowObject,
  location: { protocol: "http:", host: "localhost:8090" },
  WebSocket: FakeWebSocket,
  AudioContext: FakeAudioContext,
  AudioWorkletNode: class {},
  navigator: { mediaDevices: {} },
  ArrayBuffer,
  DataView,
  Uint8Array,
  Int16Array,
  Number,
  Math,
  Date,
  JSON,
  Error,
  Promise,
  console,
  setTimeout,
  clearTimeout,
};
vm.createContext(sandbox);
const sourceText = fs.readFileSync(
  path.join(__dirname, "..", "apps", "dashboard", "js", "mayaBrowserMic.js"),
  "utf8",
);
vm.runInContext(sourceText, sandbox, { filename: "mayaBrowserMic.js" });
const mic = windowObject.mayaBrowserMic;

async function settle() {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
}

async function negotiate(sessionId) {
  const promise = mic.connect("/api/voice/agent/ws");
  const ws = FakeWebSocket.instances.at(-1);
  ws.open();
  ws.message({ type: "audio_challenge", connection_id: `conn-${sessionId}`, session_id: sessionId });
  await settle();
  const hello = ws.sent.map((x) => {
    try { return JSON.parse(x); } catch (_) { return null; }
  }).find((x) => x?.type === "audio_hello");
  assert(hello, "challenge must produce audio_hello");
  ws.message({ type: "ready", connection_id: `conn-${sessionId}`, session_id: sessionId });
  await promise;
  return ws;
}

async function run() {
  const first = await negotiate("session-1");
  assert.strictEqual(syncedSessions.at(-1), "session-1");
  assert.strictEqual(mic.isConnected(), true);

  first.message({ type: "duck_audio" });
  first.message({ type: "resume_audio" });
  first.message({ type: "clear_audio", generation_id: 8 });
  assert.deepStrictEqual(
    playbackEvents.map((x) => [x.type, x.session_id, x.generation_id, x.turn_id]),
    [
      ["duck_audio", "session-1", 7, "turn-7"],
      ["resume_audio", "session-1", 7, "turn-7"],
      ["clear_audio", "session-1", 8, "turn-7"],
    ],
    "WS controls must be enriched with the active playback identity",
  );

  mic.disconnect();
  assert.strictEqual(endedSessions.at(-1), "session-1");
  const secondPromise = mic.connect("/api/voice/agent/ws");
  const second = FakeWebSocket.instances.at(-1);

  const eventCount = playbackEvents.length;
  const syncCount = syncedSessions.length;
  first.message({ type: "clear_audio", generation_id: 999, session_id: "session-old" });
  first.message({ type: "audio_challenge", connection_id: "old", session_id: "session-old" });
  assert.strictEqual(playbackEvents.length, eventCount, "stale socket control must be ignored");
  assert.strictEqual(syncedSessions.length, syncCount, "stale challenge must be ignored");

  second.open();
  second.message({ type: "audio_challenge", connection_id: "conn-session-2", session_id: "session-2" });
  await settle();
  second.message({ type: "ready", connection_id: "conn-session-2", session_id: "session-2" });
  await secondPromise;
  assert.strictEqual(syncedSessions.at(-1), "session-2");

  leader = false;
  assert.strictEqual(await mic.startMicrophone({ wsUrl: "/api/voice/agent/ws" }), false);
  mic.onLostLeadership();
  await new Promise((resolve) => setTimeout(resolve, 450));
  assert.strictEqual(FakeWebSocket.instances.length, 2, "observer tab must not reconnect");
  assert.strictEqual(mic.isConnected(), false);

  console.log("test_browser_mic_module: passed");
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
