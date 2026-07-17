/**
 * AUDIO-006: AudioWorklet mic capture invariants.
 * Run: node tests/test_audio_worklet_mic.js
 */

"use strict";

const fs = require("fs");
const path = require("path");

function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}

const root = path.join(__dirname, "..", "apps", "dashboard", "js");
const micSrc = fs.readFileSync(path.join(root, "mayaBrowserMic.js"), "utf8");
const workletSrc = fs.readFileSync(path.join(root, "mayaMicCapture.worklet.js"), "utf8");

function testNoScriptProcessor() {
  assert(!/createScriptProcessor/.test(micSrc), "mayaBrowserMic must not use ScriptProcessor");
  assert(!/onaudioprocess/.test(micSrc), "mayaBrowserMic must not use onaudioprocess");
  assert(/AudioWorkletNode/.test(micSrc), "mayaBrowserMic must use AudioWorkletNode");
  assert(/maya-mic-capture/.test(micSrc), "registers maya-mic-capture processor name");
}

function testWorkletRegistersProcessor() {
  assert(/registerProcessor\("maya-mic-capture"/.test(workletSrc), "worklet registers processor");
  assert(/Int16Array/.test(workletSrc), "worklet converts to PCM16");
  assert(/postMessage/.test(workletSrc), "worklet posts chunks");
  assert(/transfer|\[pcm\.buffer\]/.test(workletSrc), "transfers buffer to main thread");
}

/** Mirror worklet accumulate+flush for gap-free chunking under bursty input. */
function accumulateChunks(frames, chunkSize) {
  const pending = new Float32Array(chunkSize);
  let filled = 0;
  const out = [];
  for (const frame of frames) {
    let offset = 0;
    while (offset < frame.length) {
      const space = chunkSize - filled;
      const take = Math.min(space, frame.length - offset);
      pending.set(frame.subarray(offset, offset + take), filled);
      filled += take;
      offset += take;
      if (filled >= chunkSize) {
        out.push(Float32Array.from(pending));
        filled = 0;
      }
    }
  }
  return { chunks: out, remainder: filled };
}

function testChunkingHasNoGapsUnderUiJankSimulation() {
  // Simulate irregular render quanta (128) plus a large backlog flush (main-thread jank).
  const chunkSize = 2048;
  const frames = [];
  for (let i = 0; i < 10; i++) frames.push(new Float32Array(128));
  frames.push(new Float32Array(1280)); // backlog catch-up
  for (let i = 0; i < 6; i++) frames.push(new Float32Array(128));
  const total = frames.reduce((n, f) => n + f.length, 0);
  const { chunks, remainder } = accumulateChunks(frames, chunkSize);
  assert(chunks.length === Math.floor(total / chunkSize), "full chunks emitted");
  assert(remainder === total % chunkSize, "remainder matches");
  assert(chunks.every((c) => c.length === chunkSize), "uniform chunk size");
}

testNoScriptProcessor();
testWorkletRegistersProcessor();
testChunkingHasNoGapsUnderUiJankSimulation();
console.log("test_audio_worklet_mic: 3 passed");
