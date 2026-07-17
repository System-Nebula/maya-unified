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
  let normalVolume = 1;
  let speaking = false;
  let unlocked = false;
  let paused = false;
  let chunkCount = 0;
  const speakingListeners = new Set();
  const activeSources = new Set();
  /** Serializes chunk scheduling — async scheduleChunk must not interleave nextStart. */
  let scheduleChain = Promise.resolve();
  let scheduleGen = 0;
  /** Duplex-style generation gate — reject delayed audio from prior turns. */
  let activeGeneration = null;
  let activeSessionId = null;
  let activeTurnId = null;
  const retiredSessionIds = [];
  let lastQueuedSeq = 0;
  let lastPlayedSeq = 0;
  let playbackStartedSent = false;
  let endedTimer = null;
  let ducked = false;

  function normalizeGeneration(value) {
    return Number.isSafeInteger(value) && value >= 0 ? value : null;
  }

  function normalizeId(value) {
    return typeof value === "string" && value.trim() ? value.trim() : null;
  }

  function currentIdentity() {
    return {
      generation_id: activeGeneration,
      session_id: activeSessionId,
      turn_id: activeTurnId,
    };
  }

  function eventIdentity(ev) {
    return {
      generation_id: normalizeGeneration(ev?.generation_id),
      session_id: normalizeId(ev?.session_id),
      turn_id: normalizeId(ev?.turn_id),
    };
  }

  function sameIdentity(left, right) {
    return !!left && !!right &&
      left.generation_id === right.generation_id &&
      left.session_id === right.session_id &&
      left.turn_id === right.turn_id;
  }

  function rememberRetiredSession(sessionId) {
    const sid = normalizeId(sessionId);
    if (!sid || retiredSessionIds.includes(sid)) return;
    retiredSessionIds.push(sid);
    while (retiredSessionIds.length > 32) retiredSessionIds.shift();
  }

  function eventMatchesActive(ev) {
    const incoming = eventIdentity(ev);
    if (activeGeneration != null && incoming.generation_id !== activeGeneration) return false;
    if (activeSessionId != null && incoming.session_id !== activeSessionId) return false;
    if (activeTurnId != null && incoming.turn_id !== activeTurnId) return false;
    return activeGeneration != null || activeSessionId != null || activeTurnId != null;
  }

  function controlIsFresh(ev, { allowSessionSwitch = false } = {}) {
    const incoming = eventIdentity(ev);
    if (incoming.generation_id == null) return false;
    if (activeSessionId != null) {
      if (incoming.session_id == null) return false;
      if (incoming.session_id !== activeSessionId) {
        if (!allowSessionSwitch || retiredSessionIds.includes(incoming.session_id)) return false;
        if (activeGeneration != null && incoming.generation_id <= activeGeneration) return false;
      }
    } else if (incoming.session_id && retiredSessionIds.includes(incoming.session_id)) {
      return false;
    }
    if (activeGeneration != null && incoming.generation_id < activeGeneration) return false;
    if (activeGeneration != null && incoming.generation_id === activeGeneration) {
      if (activeTurnId != null && incoming.turn_id !== activeTurnId) return false;
      if (activeSessionId != null && incoming.session_id !== activeSessionId) return false;
    }
    return true;
  }

  function adoptIdentity(ev) {
    const incoming = eventIdentity(ev);
    const generationChanged = incoming.generation_id != null && incoming.generation_id !== activeGeneration;
    if (incoming.session_id != null) activeSessionId = incoming.session_id;
    if (incoming.generation_id != null) activeGeneration = incoming.generation_id;
    if (incoming.turn_id != null) activeTurnId = incoming.turn_id;
    else if (generationChanged) activeTurnId = null;
  }

  function syncSession(sessionId) {
    const sid = normalizeId(sessionId);
    if (!sid || sid === activeSessionId) return true;
    if (retiredSessionIds.includes(sid)) return false;
    if (activeSessionId) rememberRetiredSession(activeSessionId);
    stopAllSources("session_change", currentIdentity());
    activeSessionId = sid;
    activeGeneration = null;
    activeTurnId = null;
    restoreGainImmediate();
    return true;
  }

  function endSession(sessionId) {
    const sid = normalizeId(sessionId);
    if (!sid || sid !== activeSessionId) return false;
    const identity = currentIdentity();
    rememberRetiredSession(sid);
    stopAllSources("session_end", identity);
    activeSessionId = null;
    activeGeneration = null;
    activeTurnId = null;
    restoreGainImmediate();
    return true;
  }

  function sendPlaybackAck(payload, identity) {
    if (!payload || typeof payload !== "object") return;
    const captured = identity || currentIdentity();
    const body = {
      ...payload,
      generation_id:
        payload.generation_id != null ? payload.generation_id : captured.generation_id,
      session_id: payload.session_id != null ? payload.session_id : captured.session_id,
      turn_id: payload.turn_id != null ? payload.turn_id : captured.turn_id,
    };
    window.mayaBrowserMic?.sendControl?.(body);
  }

  function ensureCtx() {
    if (!ctx) {
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      gainNode = ctx.createGain();
      analyser = ctx.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.35;
      gainNode.connect(analyser);
      analyser.connect(ctx.destination);
      gainNode.gain.value = ducked ? 0 : volume;
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
    try {
      if (typeof ev?.data !== "string" || !ev.data || ev.data.length > 8 * 1024 * 1024) return null;
      const bin = atob(ev.data);
      if (!bin.length || bin.length > 6 * 1024 * 1024 || bin.length % 4 !== 0) return null;
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const pcm = new Float32Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 4);
      for (let i = 0; i < pcm.length; i++) {
        if (!Number.isFinite(pcm[i])) return null;
      }
      return pcm;
    } catch (_) {
      return null;
    }
  }

  function notifySpeaking(next) {
    if (speaking === next) return;
    speaking = next;
    for (const fn of speakingListeners) {
      try {
        fn(speaking);
      } catch (_) {}
    }
  }

  function stopAllSources(reason, ackIdentity) {
    const captured = ackIdentity || currentIdentity();
    scheduleGen += 1;
    scheduleChain = Promise.resolve();
    if (endedTimer) {
      clearTimeout(endedTimer);
      endedTimer = null;
    }
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
    const wasSpeaking = speaking;
    notifySpeaking(false);
    if (reason === "interrupt" || (wasSpeaking && reason === "pause")) {
      sendPlaybackAck({
        type: "playback_interrupted",
        sequence: lastPlayedSeq,
        reason: reason || "stop",
      }, captured);
    }
    playbackStartedSent = false;
  }

  function pauseOutput() {
    paused = true;
    stopAllSources("pause", currentIdentity());
    restoreGainImmediate();
  }

  function resumeOutput() {
    paused = false;
    unduck();
  }

  function scheduleChunk(pcm, sr, meta) {
    if (!pcm?.length || paused) return scheduleChain;
    const gen = scheduleGen;
    const info = meta || {};
    scheduleChain = scheduleChain
      .catch(() => undefined)
      .then(() => _scheduleChunkNow(pcm, sr, gen, info));
    return scheduleChain;
  }

  function maybeEmitPlaybackEnded(identity, epoch) {
    if (endedTimer) clearTimeout(endedTimer);
    endedTimer = setTimeout(() => {
      endedTimer = null;
      if (activeSources.size || paused || epoch !== scheduleGen) return;
      if (!sameIdentity(identity, currentIdentity())) return;
      sendPlaybackAck({
        type: "playback_ended",
        sequence: lastPlayedSeq,
      }, identity);
      playbackStartedSent = false;
    }, 40);
  }

  async function _scheduleChunkNow(pcm, sr, gen, meta) {
    if (!pcm?.length || paused || gen !== scheduleGen) return;
    await unlock();
    if (gen !== scheduleGen) return;
    const ac = ensureCtx();
    const rate = Math.max(8000, Number(sr) || 24000);
    const buf = ac.createBuffer(1, pcm.length, rate);
    buf.copyToChannel(pcm, 0);
    const src = ac.createBufferSource();
    src.buffer = buf;
    src.connect(gainNode);
    const seq = typeof meta.sequence === "number" ? meta.sequence : null;
    const identity = {
      generation_id: normalizeGeneration(meta.generation_id),
      session_id: normalizeId(meta.session_id),
      turn_id: normalizeId(meta.turn_id),
    };
    const epoch = gen;
    activeSources.add(src);
    src.onended = () => {
      activeSources.delete(src);
      if (epoch !== scheduleGen || !sameIdentity(identity, currentIdentity())) return;
      if (typeof seq === "number") {
        lastPlayedSeq = Math.max(lastPlayedSeq, seq);
        sendPlaybackAck({ type: "playback_progress", sequence: lastPlayedSeq }, identity);
      }
      if (!activeSources.size) {
        notifySpeaking(false);
        maybeEmitPlaybackEnded(identity, epoch);
      }
    };
    const now = ac.currentTime;
    if (nextStart < now) nextStart = now + 0.03;
    src.start(nextStart);
    nextStart += buf.duration;
    if (!playbackStartedSent) {
      playbackStartedSent = true;
      sendPlaybackAck({ type: "playback_started", sequence: seq }, identity);
    }
    notifySpeaking(true);
    chunkCount += 1;
  }

  function duck(factor, seconds) {
    const rawFactor = Number(factor);
    const f = Number.isFinite(rawFactor) ? Math.max(0, Math.min(1, rawFactor)) : 0.22;
    const sec = Math.max(0.01, Number(seconds) || 0.06);
    normalVolume = volume;
    ducked = true;
    if (!gainNode || !ctx) return;
    const now = ctx.currentTime;
    gainNode.gain.cancelScheduledValues(now);
    gainNode.gain.setValueAtTime(gainNode.gain.value, now);
    gainNode.gain.linearRampToValueAtTime(f * normalVolume, now + sec);
  }

  function unduck(seconds) {
    ducked = false;
    normalVolume = volume;
    if (!gainNode || !ctx) return;
    const sec = Math.max(0.01, Number(seconds) || 0.12);
    const now = ctx.currentTime;
    gainNode.gain.cancelScheduledValues(now);
    gainNode.gain.setValueAtTime(gainNode.gain.value, now);
    gainNode.gain.linearRampToValueAtTime(volume, now + sec);
  }

  function restoreGainImmediate() {
    ducked = false;
    normalVolume = volume;
    if (!gainNode || !ctx) return;
    const now = ctx.currentTime;
    gainNode.gain.cancelScheduledValues(now);
    gainNode.gain.setValueAtTime(volume, now);
  }

  function onSpeakingChange(fn) {
    if (typeof fn !== "function") return () => {};
    speakingListeners.add(fn);
    return () => speakingListeners.delete(fn);
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
      if (Number.isFinite(Number(ev.output_volume))) {
        volume = Math.max(0, Math.min(2, Number(ev.output_volume)));
        normalVolume = volume;
        if (gainNode && !ducked) gainNode.gain.value = volume;
      }
      return;
    }
    if (outputSink !== "browser") return;
    if (ev.type === "duck_audio") {
      if (eventMatchesActive(ev)) duck(ev.factor, ev.seconds);
      return;
    }
    if (ev.type === "resume_audio") {
      if (eventMatchesActive(ev)) {
        paused = false;
        unduck(ev.seconds);
      }
      return;
    }
    const leader = window.mayaVoiceLeader;
    const amLeader = !leader || leader.isLeader();
    if (ev.type === "audio_begin") {
      if (!controlIsFresh(ev, { allowSessionSwitch: true })) return;
      stopAllSources("begin", currentIdentity());
      adoptIdentity(ev);
      lastQueuedSeq = 0;
      lastPlayedSeq = 0;
      playbackStartedSent = false;
      paused = false;
      restoreGainImmediate();
      return;
    }
    if (ev.type === "clear_audio" || ev.type === "audio_stop") {
      if (!controlIsFresh(ev)) return;
      const terminalIdentity = eventIdentity(ev);
      stopAllSources("interrupt", terminalIdentity);
      adoptIdentity(ev);
      lastQueuedSeq = 0;
      lastPlayedSeq = 0;
      paused = false;
      restoreGainImmediate();
      return;
    }
    if (ev.type === "audio_queued") {
      if (!eventMatchesActive(ev)) return;
      if (typeof ev.sequence === "number") {
        lastQueuedSeq = Math.max(lastQueuedSeq, ev.sequence);
      }
      return;
    }
    if (ev.type === "audio" && ev.format === "f32le" && ev.data) {
      if (!amLeader || !eventMatchesActive(ev)) return;
      const pcm = decodeChunk(ev);
      const rate = Number(ev.sr);
      if (!pcm?.length || !Number.isFinite(rate) || rate < 8000 || rate > 192000) return;
      if (typeof ev.sequence === "number") {
        lastQueuedSeq = Math.max(lastQueuedSeq, ev.sequence);
      }
      scheduleChunk(pcm, rate, {
        sequence: ev.sequence,
        generation_id: ev.generation_id,
        session_id: ev.session_id,
        turn_id: ev.turn_id,
      });
    }
  }

  async function loadSinkFromSettings() {
    try {
      const r = await fetch("/api/voice/settings");
      if (!r.ok) return;
      const data = await r.json();
      const audio = data.settings?.audio || {};
      outputSink = audio.output_sink === "system" ? "system" : "browser";
      const configured = Number(audio.output_volume ?? 1);
      volume = Number.isFinite(configured) ? Math.max(0, Math.min(2, configured)) : 1;
      normalVolume = volume;
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
    activeGeneration() {
      return activeGeneration;
    },
    activeSessionId() {
      return activeSessionId;
    },
    activeTurnId() {
      return activeTurnId;
    },
    getAudioFrame() {
      return { level: getLevel(), bands: getSpectrumBands(), speaking };
    },
    setVolume(v) {
      const next = Number(v);
      if (!Number.isFinite(next)) return;
      volume = Math.max(0, Math.min(2, next));
      normalVolume = volume;
      if (gainNode && !ducked) gainNode.gain.value = volume;
    },
    syncSession,
    endSession,
    duck,
    unduck,
    onSpeakingChange,
    resume: unlock,
    stop: pauseOutput,
    resumeOutput,
    scheduleChunk,
    handleEvent,
    onBecameLeader() {
      // Playback resumes naturally on the next audio_begin/audio chunk.
    },
    onLostLeadership() {
      stopAllSources("leader_change");
    },
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
