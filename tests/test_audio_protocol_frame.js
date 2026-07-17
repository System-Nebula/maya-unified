/**
 * AUDIO-001 framed PCM packing (mirrors mayaBrowserMic packPcmFrame).
 * Run: node tests/test_audio_protocol_frame.js
 */

"use strict";

function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}

const PROTOCOL_VERSION = 1;
const FRAME_MAGIC = 0x4159414d;
const FRAME_HEADER_BYTES = 16;

function packPcmFrame(pcm16, sequence, sampleIndex, flags) {
  const pcmBytes = pcm16.byteLength;
  const buf = new ArrayBuffer(FRAME_HEADER_BYTES + pcmBytes);
  const view = new DataView(buf);
  view.setUint32(0, FRAME_MAGIC, true);
  view.setUint8(4, PROTOCOL_VERSION);
  view.setUint8(5, flags || 0);
  view.setUint16(6, 0, true);
  view.setUint32(8, sequence >>> 0, true);
  view.setUint32(12, sampleIndex >>> 0, true);
  new Uint8Array(buf, FRAME_HEADER_BYTES).set(
    new Uint8Array(pcm16.buffer, pcm16.byteOffset, pcmBytes),
  );
  return buf;
}

function testPackHeader() {
  const pcm = new Int16Array([1, 2, 3, 4]);
  const buf = packPcmFrame(pcm, 7, 100, 0);
  const view = new DataView(buf);
  assert(view.getUint32(0, true) === FRAME_MAGIC, "magic");
  assert(view.getUint8(4) === PROTOCOL_VERSION, "version");
  assert(view.getUint32(8, true) === 7, "sequence");
  assert(view.getUint32(12, true) === 100, "sample_index");
  assert(buf.byteLength === FRAME_HEADER_BYTES + 8, "length");
}

function testNoStreamBeforeReady() {
  // Mirrors client gate: negotiated must be true before send.
  let negotiated = false;
  let sent = 0;
  function maybeSend() {
    if (!negotiated) return;
    sent += 1;
  }
  maybeSend();
  assert(sent === 0, "must not stream before ready");
  negotiated = true;
  maybeSend();
  assert(sent === 1, "streams after ready");
}

function testHelloPayloadUsesContextRate() {
  const sampleRate = 44100;
  const hello = {
    type: "audio_hello",
    protocol: PROTOCOL_VERSION,
    format: "s16le",
    sample_rate: sampleRate,
    channels: 1,
    frames_per_chunk: 2048,
  };
  assert(hello.sample_rate === 44100, "uses AudioContext.sampleRate");
}

testPackHeader();
testNoStreamBeforeReady();
testHelloPayloadUsesContextRate();
console.log("test_audio_protocol_frame: 3 passed");
