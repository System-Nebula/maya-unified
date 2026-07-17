/** Execute the shipped browser audio module against a deterministic WebAudio shim. */
"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

class FakeParam {
  constructor(value = 1) { this.value = value; }
  cancelScheduledValues() {}
  setValueAtTime(value) { this.value = value; }
  linearRampToValueAtTime(value) { this.value = value; }
}

class FakeSource {
  constructor() {
    this.buffer = null;
    this.onended = null;
    this.started = false;
    this.stopped = false;
  }
  connect() {}
  disconnect() {}
  start() { this.started = true; }
  stop() { this.stopped = true; }
}

class FakeAudioContext {
  static instances = [];
  constructor() {
    this.state = "running";
    this.currentTime = 1;
    this.sampleRate = 48000;
    this.destination = {};
    this.sources = [];
    this.gain = null;
    FakeAudioContext.instances.push(this);
  }
  async resume() { this.state = "running"; }
  createGain() {
    this.gain = { gain: new FakeParam(1), connect() {} };
    return this.gain;
  }
  createAnalyser() {
    return {
      fftSize: 2048,
      frequencyBinCount: 1024,
      smoothingTimeConstant: 0,
      connect() {},
      getFloatTimeDomainData(a) { a.fill(0); },
      getFloatFrequencyData(a) { a.fill(-120); },
    };
  }
  createBuffer(_channels, length, rate) {
    return {
      duration: length / rate,
      copyToChannel() {},
    };
  }
  createBufferSource() {
    const source = new FakeSource();
    this.sources.push(source);
    return source;
  }
}

const controls = [];
const windowObject = {
  AudioContext: FakeAudioContext,
  mayaVoiceLeader: { isLeader: () => true },
  mayaBrowserMic: { sendControl: (payload) => controls.push(payload) },
  mayaAgentEvents: { subscribe() {} },
};
const sandbox = {
  window: windowObject,
  document: { addEventListener() {} },
  fetch: async () => ({ ok: false, json: async () => ({}) }),
  atob: (value) => Buffer.from(value, "base64").toString("binary"),
  Float32Array,
  Uint8Array,
  Number,
  Math,
  Promise,
  Set,
  console,
  setTimeout,
  clearTimeout,
  setInterval,
  clearInterval,
};
vm.createContext(sandbox);
const sourceText = fs.readFileSync(
  path.join(__dirname, "..", "apps", "dashboard", "js", "mayaBrowserAudio.js"),
  "utf8",
);
vm.runInContext(sourceText, sandbox, { filename: "mayaBrowserAudio.js" });
const audio = windowObject.mayaBrowserAudioOutput;

function encodedFloat32(values) {
  const pcm = new Float32Array(values);
  return Buffer.from(pcm.buffer, pcm.byteOffset, pcm.byteLength).toString("base64");
}

function event(type, overrides = {}) {
  return {
    type,
    session_id: "session-1",
    turn_id: "turn-3",
    generation_id: 3,
    ...overrides,
  };
}

async function settle() {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
}

async function run() {
  assert.strictEqual(await audio.resume(), true);
  const context = FakeAudioContext.instances[0];
  assert(context, "module should create the fake AudioContext");
  assert.strictEqual(audio.syncSession("session-1"), true);

  audio.handleEvent(event("audio_begin"));
  audio.duck(0.2, 0.01);
  assert(context.gain.gain.value < 1, "duck must lower output gain");

  audio.handleEvent(event("audio", {
    format: "f32le",
    data: encodedFloat32([0.1, -0.1, 0.2]),
    sr: 24000,
    sequence: 1,
  }));
  await settle();
  assert.strictEqual(context.sources.length, 1, "valid PCM must create one source");
  const oldSource = context.sources[0];
  assert(controls.some((x) => x.type === "playback_started" &&
    x.session_id === "session-1" && x.turn_id === "turn-3" && x.generation_id === 3));

  audio.handleEvent(event("clear_audio", { generation_id: 2 }));
  assert.strictEqual(audio.activeGeneration(), 3, "stale clear must not roll generation back");
  assert.strictEqual(oldSource.stopped, false, "stale clear must not stop current audio");

  audio.handleEvent(event("audio_stop", {
    session_id: "foreign-session",
    generation_id: 99,
  }));
  assert.strictEqual(oldSource.stopped, false, "foreign-session stop must be ignored");
  audio.handleEvent(event("audio_stop", { turn_id: "foreign-turn" }));
  assert.strictEqual(oldSource.stopped, false, "same-generation foreign turn must be ignored");

  audio.handleEvent(event("resume_audio"));
  assert.strictEqual(context.gain.gain.value, 1, "resume must restore configured gain");
  audio.setVolume(0);
  assert.strictEqual(context.gain.gain.value, 0, "setVolume(0) must remain muted");
  audio.setVolume(1);

  const sourceCount = context.sources.length;
  audio.handleEvent(event("audio", { format: "f32le", data: "!!!", sr: 24000 }));
  audio.handleEvent(event("audio", {
    format: "f32le",
    data: Buffer.from([1, 2, 3]).toString("base64"),
    sr: 24000,
  }));
  audio.handleEvent(event("audio", {
    format: "f32le",
    data: encodedFloat32([Number.NaN]),
    sr: 24000,
  }));
  audio.handleEvent(event("audio", {
    format: "f32le",
    data: encodedFloat32([0.1]),
    sr: 1,
  }));
  await settle();
  assert.strictEqual(context.sources.length, sourceCount, "malformed PCM/rate must be ignored");

  audio.handleEvent(event("audio_begin", { generation_id: 5, turn_id: "turn-5" }));
  assert.strictEqual(oldSource.stopped, true, "fresh begin must stop prior sources");
  const beforeOldEnded = controls.length;
  oldSource.onended();
  await new Promise((resolve) => setTimeout(resolve, 60));
  assert.strictEqual(controls.length, beforeOldEnded, "old source callback must not ack a new turn");

  audio.handleEvent(event("audio", {
    generation_id: 5,
    turn_id: "turn-5",
    format: "f32le",
    data: encodedFloat32([0.2, 0.1]),
    sr: 24000,
    sequence: 2,
  }));
  await settle();
  const currentSource = context.sources.at(-1);
  audio.duck(0.2, 0.01);
  audio.handleEvent(event("audio_stop", { generation_id: 6, turn_id: "turn-5" }));
  assert.strictEqual(currentSource.stopped, true, "fresh stop must stop current source");
  assert.strictEqual(context.gain.gain.value, 1, "terminal stop must restore gain");
  assert(controls.some((x) => x.type === "playback_interrupted" &&
    x.generation_id === 6 && x.session_id === "session-1" && x.turn_id === "turn-5"));

  console.log("test_browser_audio_module: passed");
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
