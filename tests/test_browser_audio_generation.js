/**
 * Behavioral checks for mayaBrowserAudio generation/session/turn filtering.
 * Run: node tests/test_browser_audio_generation.js
 */

"use strict";

function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}

/** Mirrors mayaBrowserAudio.js generation gates. */
function generationMatches(activeGeneration, eventGeneration) {
  if (eventGeneration == null || activeGeneration == null) return true;
  return eventGeneration === activeGeneration;
}

function shouldApplyStop(activeGeneration, eventGeneration) {
  if (eventGeneration == null || activeGeneration == null) return true;
  return eventGeneration >= activeGeneration;
}

function sessionMatches(activeSessionId, eventSessionId) {
  if (eventSessionId == null || activeSessionId == null) return true;
  return eventSessionId === activeSessionId;
}

function turnMatches(activeTurnId, eventTurnId) {
  if (eventTurnId == null || activeTurnId == null) return true;
  return eventTurnId === activeTurnId;
}

function applyEvent(state, ev) {
  if (!ev) return state;
  if (ev.type === "audio_begin" || ev.type === "clear_audio") {
    if (typeof ev.generation_id === "number") {
      state.activeGeneration = ev.generation_id;
    }
    if (typeof ev.session_id === "string" && ev.session_id) {
      state.activeSessionId = ev.session_id;
    }
    if (typeof ev.turn_id === "string" && ev.turn_id) {
      state.activeTurnId = ev.turn_id;
    }
    state.stopped += 1;
    state.chunks = [];
    return state;
  }
  if (ev.type === "audio_stop") {
    if (!shouldApplyStop(state.activeGeneration, ev.generation_id)) {
      state.ignoredStops += 1;
      return state;
    }
    if (typeof ev.generation_id === "number") {
      state.activeGeneration = ev.generation_id;
    }
    if (typeof ev.session_id === "string" && ev.session_id) {
      state.activeSessionId = ev.session_id;
    }
    if (typeof ev.turn_id === "string" && ev.turn_id) {
      state.activeTurnId = ev.turn_id;
    }
    state.stopped += 1;
    state.chunks = [];
    return state;
  }
  if (ev.type === "audio") {
    if (
      !sessionMatches(state.activeSessionId, ev.session_id) ||
      !turnMatches(state.activeTurnId, ev.turn_id) ||
      !generationMatches(state.activeGeneration, ev.generation_id)
    ) {
      state.ignoredChunks += 1;
      return state;
    }
    state.chunks.push(ev.data);
  }
  return state;
}

function fresh() {
  return {
    activeGeneration: null,
    activeSessionId: null,
    activeTurnId: null,
    chunks: [],
    stopped: 0,
    ignoredChunks: 0,
    ignoredStops: 0,
  };
}

function testDelayedOldChunkIgnoredAfterRestart() {
  const state = fresh();
  applyEvent(state, { type: "audio_begin", generation_id: 1 });
  applyEvent(state, { type: "audio", generation_id: 1, data: "old-a" });
  applyEvent(state, { type: "audio_stop", generation_id: 2 });
  applyEvent(state, { type: "audio_begin", generation_id: 3 });
  applyEvent(state, { type: "audio", generation_id: 1, data: "stale" });
  applyEvent(state, { type: "audio", generation_id: 3, data: "fresh" });
  assert(state.ignoredChunks === 1, "old chunk must be ignored");
  assert(state.chunks.join(",") === "fresh", "only current generation plays");
  assert(state.activeGeneration === 3, "active generation follows restart");
}

function testLateAudioStopCannotStopNewTurn() {
  const state = fresh();
  applyEvent(state, { type: "audio_begin", generation_id: 5 });
  applyEvent(state, { type: "audio", generation_id: 5, data: "a" });
  applyEvent(state, { type: "audio_stop", generation_id: 4 });
  assert(state.ignoredStops === 1, "stale audio_stop must be ignored");
  assert(state.chunks.join(",") === "a", "new turn audio must keep playing");
  applyEvent(state, { type: "audio", generation_id: 5, data: "b" });
  assert(state.chunks.join(",") === "a,b", "playback continues after stale stop");
}

function testStopAdvancesActiveGeneration() {
  const state = fresh();
  applyEvent(state, { type: "audio_begin", generation_id: 1 });
  applyEvent(state, { type: "audio", generation_id: 1, data: "a" });
  applyEvent(state, { type: "audio_stop", generation_id: 2 });
  assert(state.activeGeneration === 2, "stop adopts advanced generation");
  assert(state.chunks.length === 0, "stop clears queued/playing audio");
  applyEvent(state, { type: "audio", generation_id: 1, data: "late" });
  assert(state.ignoredChunks === 1, "pre-stop chunks are rejected");
}

function testForeignSessionAudioIgnored() {
  const state = fresh();
  applyEvent(state, { type: "audio_begin", generation_id: 1, session_id: "s_a" });
  applyEvent(state, { type: "audio", generation_id: 1, session_id: "s_b", data: "x" });
  applyEvent(state, { type: "audio", generation_id: 1, session_id: "s_a", data: "ok" });
  assert(state.ignoredChunks === 1, "other session audio ignored");
  assert(state.chunks.join(",") === "ok", "matching session plays");
}

function testForeignTurnAudioIgnored() {
  const state = fresh();
  applyEvent(state, {
    type: "audio_begin",
    generation_id: 1,
    session_id: "s_a",
    turn_id: "t_1",
  });
  applyEvent(state, {
    type: "audio",
    generation_id: 1,
    session_id: "s_a",
    turn_id: "t_old",
    data: "stale-turn",
  });
  applyEvent(state, {
    type: "audio",
    generation_id: 1,
    session_id: "s_a",
    turn_id: "t_1",
    data: "ok",
  });
  assert(state.ignoredChunks === 1, "other turn audio ignored");
  assert(state.chunks.join(",") === "ok", "matching turn plays");
}

testDelayedOldChunkIgnoredAfterRestart();
testLateAudioStopCannotStopNewTurn();
testStopAdvancesActiveGeneration();
testForeignSessionAudioIgnored();
testForeignTurnAudioIgnored();
console.log("test_browser_audio_generation: 5 passed");
