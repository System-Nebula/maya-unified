/**
 * AUDIO-005 browser bufferedAmount drop policy.
 * Run: node tests/test_browser_backpressure.js
 */

"use strict";

function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}

const WS_HIGH_WATER = 256 * 1024;
const WS_LOW_WATER = 64 * 1024;

function decideSend(state, buffered, frameSamples) {
  const events = [];
  if (buffered > WS_HIGH_WATER) state.wsBlocked = true;
  if (state.wsBlocked) {
    if (buffered > WS_LOW_WATER) {
      state.sequence = (state.sequence + 1) >>> 0;
      state.sampleIndex = (state.sampleIndex + frameSamples) >>> 0;
      state.clientDrops += 1;
      events.push("drop");
      return { sent: false, events };
    }
    state.wsBlocked = false;
  }
  state.sequence = (state.sequence + 1) >>> 0;
  state.sampleIndex = (state.sampleIndex + frameSamples) >>> 0;
  events.push("send");
  return { sent: true, events };
}

function testDropsAdvanceTimeline() {
  const state = { wsBlocked: false, clientDrops: 0, sequence: 0, sampleIndex: 0 };
  const r1 = decideSend(state, WS_HIGH_WATER + 1, 2048);
  assert(!r1.sent, "must drop above high water");
  assert(state.sequence === 1, "sequence advances on drop");
  assert(state.sampleIndex === 2048, "sample index advances on drop");
  assert(state.clientDrops === 1, "drop counted");
}

function testResumesBelowLowWater() {
  const state = { wsBlocked: true, clientDrops: 2, sequence: 5, sampleIndex: 10000 };
  const r = decideSend(state, WS_LOW_WATER - 1, 2048);
  assert(r.sent, "resumes when buffer drains");
  assert(state.wsBlocked === false, "clears blocked flag");
}

function testStaysBlockedBetweenWatermarks() {
  const state = { wsBlocked: true, clientDrops: 0, sequence: 0, sampleIndex: 0 };
  const r = decideSend(state, (WS_HIGH_WATER + WS_LOW_WATER) / 2, 512);
  assert(!r.sent, "stay dropped until low water");
  assert(state.clientDrops === 1);
}

testDropsAdvanceTimeline();
testResumesBelowLowWater();
testStaysBlockedBetweenWatermarks();
console.log("test_browser_backpressure: 3 passed");
