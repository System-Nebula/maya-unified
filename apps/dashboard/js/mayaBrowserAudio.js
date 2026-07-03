/**
 * Browser TTS playback — receives f32le PCM chunks from SSE and plays via Web Audio API.
 */
(function () {
  "use strict";

  let ctx = null;
  let gainNode = null;
  let analyser = null;
  let nextStart = 0;
  let outputSink = "browser";
  let volume = 1;
  let speaking = false;
  let unlocked = false;
  let paused = false;
  let chunkCount = 0;
  const activeSources = new Set();

  function ensureCtx() {
    if (!ctx) {
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      gainNode = ctx.createGain();
      analyser = ctx.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.35;
      gainNode.connect(analyser);
      analyser.connect(ctx.destination);
      gainNode.gain.value = volume;
    }
    return ctx;
  }

  async function unlock() {
    const ac = ensureCtx();
    if (ac.state === "suspended") {
      try {
        await ac.resume();
      } catch (_) {}
    }
    unlocked = ac.state === "running";
    return unlocked;
  }

  function decodeChunk(ev) {
    const bin = atob(ev.data || "");
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new Float32Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 4);
  }

  function stopAllSources() {
    for (const src of activeSources) {
      try {
        src.stop();
      } catch (_) {}
      try {
        src.disconnect();
      } catch (_) {}
    }
    activeSources.clear();
    nextStart = 0;
    speaking = false;
  }

  function pauseOutput() {
    paused = true;
    stopAllSources();
  }

  function resumeOutput() {
    paused = false;
  }

  async function scheduleChunk(pcm, sr) {
    if (!pcm?.length || paused) return;
    await unlock();
    const ac = ensureCtx();
    const rate = Math.max(8000, Number(sr) || 24000);
    const buf = ac.createBuffer(1, pcm.length, rate);
    buf.copyToChannel(pcm, 0);
    const src = ac.createBufferSource();
    src.buffer = buf;
    src.connect(gainNode);
    activeSources.add(src);
    src.onended = () => {
      activeSources.delete(src);
      if (!activeSources.size) speaking = false;
    };
    const now = ac.currentTime;
    if (nextStart < now) nextStart = now + 0.03;
    src.start(nextStart);
    nextStart += buf.duration;
    speaking = true;
    chunkCount += 1;
  }

  function getLevel() {
    if (!analyser || !speaking) return 0;
    const data = new Float32Array(analyser.fftSize);
    analyser.getFloatTimeDomainData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
    return Math.sqrt(sum / data.length);
  }

  function getSpectrumBands(nBands = 56) {
    if (!analyser || !speaking) return [];
    const freqs = new Float32Array(analyser.frequencyBinCount);
    analyser.getFloatFrequencyData(freqs);
    const sr = ctx?.sampleRate || 48000;
    const fmax = Math.min(sr / 2, 16000);
    const edges = [];
    for (let i = 0; i <= nBands; i++) {
      edges.push(40 * Math.pow(fmax / 40, i / nBands));
    }
    const out = [];
    const binHz = sr / analyser.fftSize;
    for (let i = 0; i < nBands; i++) {
      const lo = edges[i];
      const hi = edges[i + 1];
      const i0 = Math.max(0, Math.floor(lo / binHz));
      const i1 = Math.min(freqs.length - 1, Math.ceil(hi / binHz));
      let peak = -120;
      for (let j = i0; j <= i1; j++) peak = Math.max(peak, freqs[j]);
      const norm = Math.max(0, Math.min(1, (peak + 65) / 65));
      out.push({ f: Math.round(0.5 * (lo + hi) * 10) / 10, v: Math.round(norm * 10000) / 10000 });
    }
    return out;
  }

  function handleEvent(ev) {
    if (!ev) return;
    if (ev.type === "settings") {
      if (ev.output_sink) outputSink = ev.output_sink === "system" ? "system" : "browser";
      if (typeof ev.output_volume === "number" && gainNode) {
        volume = Math.max(0, Math.min(2, ev.output_volume));
        gainNode.gain.value = volume;
      }
      return;
    }
    if (outputSink !== "browser") return;
    if (ev.type === "audio_begin" || ev.type === "audio_stop") {
      paused = false;
      stopAllSources();
      return;
    }
    if (ev.type === "audio" && ev.format === "f32le" && ev.data) {
      scheduleChunk(decodeChunk(ev), ev.sr);
    }
  }

  async function loadSinkFromSettings() {
    try {
      const r = await fetch("/api/voice/settings");
      if (!r.ok) return;
      const data = await r.json();
      const audio = data.settings?.audio || {};
      outputSink = audio.output_sink === "system" ? "system" : "browser";
      volume = Number(audio.output_volume ?? 1);
      if (gainNode) gainNode.gain.value = volume;
    } catch (_) {}
  }

  function bindEvents() {
    if (!window.mayaAgentEvents) return false;
    window.mayaAgentEvents.subscribe(handleEvent);
    return true;
  }

  window.mayaBrowserAudioOutput = {
    isBrowserSink() {
      return outputSink === "browser";
    },
    isSpeaking() {
      return speaking;
    },
    isUnlocked() {
      return unlocked;
    },
    getAudioFrame() {
      return { level: getLevel(), bands: getSpectrumBands(), speaking };
    },
    setVolume(v) {
      volume = Math.max(0, Math.min(2, Number(v) || 1));
      if (gainNode) gainNode.gain.value = volume;
    },
    resume: unlock,
    stop: pauseOutput,
    resumeOutput,
    handleEvent,
  };

  if (!bindEvents()) {
    const wait = setInterval(() => {
      if (bindEvents()) clearInterval(wait);
    }, 50);
  }

  document.addEventListener(
    "click",
    () => {
      unlock().then(() => {
        const shell = window.Alpine?.store?.("mayaShell");
        if (shell && window.mayaBrowserAudioOutput?.isUnlocked?.()) {
          shell.browserAudioHint = "";
        }
      });
    },
    { capture: true, passive: true },
  );

  loadSinkFromSettings();
})();
