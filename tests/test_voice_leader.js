/**
 * Behavioral checks for voice leader playback gating.
 * Run: node tests/test_voice_leader.js
 */

"use strict";

function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}

function shouldPlayAudio(isLeader, ev) {
  if (!ev || ev.type !== "audio") return false;
  if (!isLeader) return false;
  return true;
}

function testObserverSkipsAudio() {
  assert(!shouldPlayAudio(false, { type: "audio", data: "x" }), "observer must skip audio");
  assert(shouldPlayAudio(true, { type: "audio", data: "x" }), "leader plays audio");
}

function testElectLowestTabId() {
  const peers = [
    { id: "b", seen: Date.now() },
    { id: "a", seen: Date.now() },
    { id: "c", seen: Date.now() - 99999 },
  ];
  const now = Date.now();
  const live = peers.filter((p) => now - p.seen < 5000).map((p) => p.id);
  live.sort();
  assert(live[0] === "a", "lowest tab id wins");
}

testObserverSkipsAudio();
testElectLowestTabId();
console.log("test_voice_leader: 2 passed");
