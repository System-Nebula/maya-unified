/**
 * Browser mic ingress — negotiates AUDIO-001, then streams framed s16le PCM.
 */
(function () {
  "use strict";

  const PROTOCOL_VERSION = 1;
  const FRAME_MAGIC = 0x4159414d; // 'MAYA' little-endian
  const FRAME_HEADER_BYTES = 16;
  const FRAMES_PER_CHUNK = 2048;

  const state = {
    ws: null,
    stream: null,
    context: null,
    source: null,
    worklet: null,
    silentGain: null,
    workletModuleUrl: "/dashboard/js/mayaMicCapture.worklet.js",
    workletLoadedForContext: null,
    gain: 1,
    connected: false,
    negotiated: false,
    micActive: false,
    playbackUnsub: null,
    intentionalClose: false,
    wantSession: false,
    wsPath: "/api/voice/agent/ws",
    reconnectAttempt: 0,
    reconnectTimer: null,
    sequence: 0,
    sampleIndex: 0,
    sessionId: null,
    pendingHello: null,
    wsBlocked: false,
    clientDrops: 0,
    lastGapNotifyAt: 0,
    captureSettings: null,
    connectionId: null,
    connectPromise: null,
  };

  // Drop when the socket send buffer is building latency (AUDIO-005).
  const WS_HIGH_WATER = 256 * 1024;
  const WS_LOW_WATER = 64 * 1024;

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
    new Uint8Array(buf, FRAME_HEADER_BYTES).set(new Uint8Array(pcm16.buffer, pcm16.byteOffset, pcmBytes));
    return buf;
  }

  function wsUrl(path) {
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const p = path || "/api/voice/agent/ws";
    return `${protocol}://${location.host}${p}`;
  }

  function reportPlayback(speaking) {
    if (state.ws && state.ws.readyState === WebSocket.OPEN && state.negotiated) {
      const audio = window.mayaBrowserAudioOutput;
      state.ws.send(JSON.stringify({
        type: "playback_state",
        speaking: !!speaking,
        session_id: state.sessionId || audio?.activeSessionId?.() || undefined,
        generation_id: audio?.activeGeneration?.() ?? undefined,
        turn_id: audio?.activeTurnId?.() || undefined,
      }));
    }
  }

  function sendControl(payload) {
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return false;
    try {
      state.ws.send(JSON.stringify(payload || {}));
      return true;
    } catch (_) {
      return false;
    }
  }

  function bindPlaybackReporter() {
    if (state.playbackUnsub) return;
    const audio = window.mayaBrowserAudioOutput;
    if (!audio || !audio.onSpeakingChange) return;
    state.playbackUnsub = audio.onSpeakingChange((speaking) => reportPlayback(speaking));
  }

  function unbindPlaybackReporter() {
    if (state.playbackUnsub) {
      state.playbackUnsub();
      state.playbackUnsub = null;
    }
  }

  function clearReconnectTimer() {
    if (state.reconnectTimer) {
      clearTimeout(state.reconnectTimer);
      state.reconnectTimer = null;
    }
  }

  function isVoiceLeader() {
    const leader = window.mayaVoiceLeader;
    return !leader || leader.isLeader();
  }

  function scheduleReconnect() {
    if (state.intentionalClose || !state.wantSession || state.reconnectTimer || !isVoiceLeader()) return;
    const delay = Math.min(8000, 400 * Math.pow(2, state.reconnectAttempt));
    state.reconnectAttempt += 1;
    state.reconnectTimer = setTimeout(() => {
      state.reconnectTimer = null;
      if (!isVoiceLeader()) return;
      reconnect().catch(() => scheduleReconnect());
    }, delay);
  }

  async function reconnect() {
    if (state.intentionalClose || !state.wantSession || !isVoiceLeader()) return;
    await connect(state.wsPath);
    if (!isVoiceLeader()) return;
    if (state.stream) {
      state.micActive = true;
    } else {
      await startMicrophone({ wsUrl: state.wsPath, gain: state.gain });
    }
    state.reconnectAttempt = 0;
  }

  async function ensureAudioContext() {
    if (!state.context) {
      state.context = new AudioContext({ sampleRate: 48000, latencyHint: "interactive" });
      state.workletLoadedForContext = null;
    }
    if (state.context.state === "suspended") {
      try {
        await state.context.resume();
      } catch (_) {}
    }
    return state.context;
  }

  async function ensureWorkletModule(context) {
    if (!context.audioWorklet || typeof context.audioWorklet.addModule !== "function") {
      throw new Error("AudioWorklet is required for browser mic capture");
    }
    if (state.workletLoadedForContext === context) return;
    await context.audioWorklet.addModule(state.workletModuleUrl);
    state.workletLoadedForContext = context;
  }

  function sendPcmChunk(pcm16) {
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN || !state.negotiated) return;
    const n = pcm16.length;
    const buffered = state.ws.bufferedAmount || 0;
    if (buffered > WS_HIGH_WATER) {
      state.wsBlocked = true;
    }
    if (state.wsBlocked) {
      if (buffered > WS_LOW_WATER) {
        // Freshness over completeness: drop this frame but advance timeline.
        state.sequence = (state.sequence + 1) >>> 0;
        state.sampleIndex = (state.sampleIndex + n) >>> 0;
        state.clientDrops += 1;
        const now = Date.now();
        if (now - state.lastGapNotifyAt > 250) {
          state.lastGapNotifyAt = now;
          sendControl({
            type: "client_gap",
            dropped: state.clientDrops,
            sequence: state.sequence,
            sample_index: state.sampleIndex,
            buffered_amount: buffered,
          });
        }
        return;
      }
      state.wsBlocked = false;
    }
    const seq = state.sequence;
    const sampleIndex = state.sampleIndex;
    state.sequence = (state.sequence + 1) >>> 0;
    state.sampleIndex = (state.sampleIndex + n) >>> 0;
    try {
      state.ws.send(packPcmFrame(pcm16, seq, sampleIndex, 0));
    } catch (_) {}
  }

  function readTrackSettings(stream) {
    try {
      const track = stream && stream.getAudioTracks && stream.getAudioTracks()[0];
      if (!track || !track.getSettings) return null;
      const s = track.getSettings();
      return {
        sampleRate: s.sampleRate,
        channelCount: s.channelCount,
        echoCancellation: s.echoCancellation,
        noiseSuppression: s.noiseSuppression,
        autoGainControl: s.autoGainControl,
        deviceId: s.deviceId,
      };
    } catch (_) {
      return null;
    }
  }

  function sendAudioHello() {
    const ctx = state.context;
    const sampleRate = (ctx && ctx.sampleRate) || 48000;
    const payload = {
      type: "audio_hello",
      protocol: PROTOCOL_VERSION,
      format: "s16le",
      sample_rate: sampleRate,
      channels: 1,
      frames_per_chunk: FRAMES_PER_CHUNK,
      session_id: state.sessionId || undefined,
    };
    try {
      state.ws.send(JSON.stringify(payload));
    } catch (_) {}
  }

  function enrichPlaybackEvent(data) {
    const audio = window.mayaBrowserAudioOutput;
    return {
      ...data,
      session_id: data.session_id || state.sessionId || audio?.activeSessionId?.() || undefined,
      generation_id: data.generation_id ?? audio?.activeGeneration?.() ?? undefined,
      turn_id: data.turn_id || audio?.activeTurnId?.() || undefined,
    };
  }

  function handleWsMessage(event, ws) {
    if (!ws || state.ws !== ws) return;
    let data;
    try {
      data = JSON.parse(event.data);
    } catch (_) {
      return;
    }
    if (data.type === "ping") {
      if (ws.readyState === WebSocket.OPEN) {
        try {
          ws.send(
            JSON.stringify({
              type: "pong",
              ts: data.ts || Date.now(),
              connection_id: data.connection_id,
            }),
          );
        } catch (_) {}
      }
      return;
    }
    if (data.type === "audio_challenge") {
      state.connectionId = data.connection_id || state.connectionId;
      state.sessionId = data.session_id || state.sessionId;
      window.mayaBrowserAudioOutput?.syncSession?.(state.sessionId);
      state.negotiated = false;
      state.sequence = 0;
      state.sampleIndex = 0;
      if (state.pendingHello) {
        state.pendingHello.resolveChallenge(data);
      } else if (ws.readyState === WebSocket.OPEN) {
        // Reconnect mid-session: answer immediately once context exists.
        ensureAudioContext().then(() => sendAudioHello()).catch(() => {});
      }
      return;
    }
    if (data.type === "ready") {
      if (state.connectionId && data.connection_id && data.connection_id !== state.connectionId) return;
      state.sessionId = data.session_id || state.sessionId;
      window.mayaBrowserAudioOutput?.syncSession?.(state.sessionId);
      state.negotiated = true;
      state.sequence = 0;
      state.sampleIndex = 0;
      if (state.pendingHello) {
        state.pendingHello.resolveReady(data);
      }
      return;
    }
    if (data.type === "error" && data.message && String(data.message).indexOf("audio_hello") >= 0) {
      if (state.pendingHello) {
        state.pendingHello.reject(new Error(data.message));
      }
      return;
    }
    if (data.type === "duck_audio" || data.type === "clear_audio" || data.type === "resume_audio") {
      window.mayaBrowserAudioOutput?.handleEvent?.(enrichPlaybackEvent(data));
    }
  }

  function connect(wsPath) {
    if (state.ws && state.ws.readyState <= 1 && state.negotiated) {
      return Promise.resolve(true);
    }
    if (state.connectPromise) return state.connectPromise;
    const attempt = new Promise((resolve, reject) => {
      state.wsPath = wsPath || state.wsPath || "/api/voice/agent/ws";
      state.intentionalClose = false;
      state.negotiated = false;
      const ws = new WebSocket(wsUrl(state.wsPath));
      state.ws = ws;
      ws.binaryType = "arraybuffer";

      let settled = false;
      const pending = {
        challengeWaiter: null,
        readyWaiter: null,
        gotChallenge: null,
        gotReady: null,
        resolveChallenge(data) {
          this.gotChallenge = data || true;
          if (this.challengeWaiter) {
            const w = this.challengeWaiter;
            this.challengeWaiter = null;
            w();
          }
        },
        resolveReady(data) {
          this.gotReady = data || true;
          if (this.readyWaiter) {
            const w = this.readyWaiter;
            this.readyWaiter = null;
            w();
          }
        },
        waitChallenge(timeoutMs) {
          if (this.gotChallenge) return Promise.resolve();
          return new Promise((res, rej) => {
            const t = setTimeout(() => rej(new Error("audio_challenge timeout")), timeoutMs);
            this.challengeWaiter = () => {
              clearTimeout(t);
              res();
            };
          });
        },
        waitReady(timeoutMs) {
          if (this.gotReady) return Promise.resolve();
          return new Promise((res, rej) => {
            const t = setTimeout(() => rej(new Error("audio ready timeout")), timeoutMs);
            this.readyWaiter = () => {
              clearTimeout(t);
              res();
            };
          });
        },
        reject(err) {
          if (!settled) {
            settled = true;
            if (state.pendingHello === this) {
              state.pendingHello = null;
            }
            reject(err);
          }
        },
      };
      state.pendingHello = pending;

      const fail = (err) => {
        if (!settled) {
          settled = true;
          if (state.pendingHello === pending) {
            state.pendingHello = null;
          }
          reject(err instanceof Error ? err : new Error(String(err || "WebSocket failed")));
        }
      };

      ws.onopen = async () => {
        if (state.ws !== ws || !isVoiceLeader()) {
          try { ws.close(); } catch (_) {}
          return;
        }
        state.connected = true;
        bindPlaybackReporter();
        try {
          await ensureAudioContext();
          await pending.waitChallenge(8000);
          sendAudioHello();
          await pending.waitReady(8000);
          if (!settled) {
            settled = true;
            if (state.pendingHello === pending) {
              state.pendingHello = null;
            }
            resolve(true);
          }
        } catch (err) {
          fail(err);
          try {
            ws.close();
          } catch (_) {}
        }
      };
      ws.onerror = () => {
        if (state.ws !== ws) return;
        state.connected = false;
        fail(new Error("WebSocket connection failed"));
      };
      ws.onclose = () => {
        // Ignore stale sockets after a replacement connect.
        if (state.ws !== ws) return;
        state.connected = false;
        state.negotiated = false;
        state.ws = null;
        // Never leave isActive true with a dead WebSocket.
        state.micActive = false;
        if (state.pendingHello === pending) {
          state.pendingHello = null;
          fail(new Error("WebSocket closed before ready"));
        }
        if (!state.intentionalClose && state.wantSession) {
          scheduleReconnect();
        }
      };
      ws.onmessage = (event) => handleWsMessage(event, ws);
    });
    state.connectPromise = attempt;
    return attempt.finally(() => {
      if (state.connectPromise === attempt) state.connectPromise = null;
    });
  }

  async function startMicrophone(options) {
    const opts = options || {};
    state.wsPath = opts.wsUrl || state.wsPath || "/api/voice/agent/ws";
    const requestedGain = Number(opts.gain);
    if (Number.isFinite(requestedGain)) state.gain = requestedGain;
    state.wantSession = true;
    state.intentionalClose = false;
    if (!isVoiceLeader()) return false;
    await ensureAudioContext();
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN || !state.negotiated) {
      await connect(opts.wsUrl || state.wsPath || "/api/voice/agent/ws");
    }
    if (state.stream) {
      state.micActive = true;
      return true;
    }

    const constraints = {
      audio: {
        channelCount: 1,
        sampleRate: 48000,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    };
    if (opts.deviceId) {
      constraints.audio.deviceId = { exact: opts.deviceId };
    }

    state.stream = await navigator.mediaDevices.getUserMedia(constraints);
    state.captureSettings = readTrackSettings(state.stream);
    const context = state.context;
    await ensureWorkletModule(context);
    state.source = context.createMediaStreamSource(state.stream);
    state.worklet = new AudioWorkletNode(context, "maya-mic-capture", {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      channelCount: 1,
      processorOptions: { chunkSize: FRAMES_PER_CHUNK, gain: state.gain },
    });
    state.silentGain = context.createGain();
    state.silentGain.gain.value = 0;
    state.source.connect(state.worklet);
    state.worklet.connect(state.silentGain);
    state.silentGain.connect(context.destination);
    state.sequence = 0;
    state.sampleIndex = 0;
    state.clientDrops = 0;
    state.wsBlocked = false;
    state.worklet.port.onmessage = (ev) => {
      const data = ev.data;
      if (!data || data.type !== "pcm" || !data.buffer) return;
      sendPcmChunk(new Int16Array(data.buffer));
    };
    try {
      state.worklet.port.postMessage({ type: "reset" });
      state.worklet.port.postMessage({ type: "gain", value: state.gain });
    } catch (_) {}
    state.micActive = true;
    reportPlayback(window.mayaBrowserAudioOutput?.isSpeaking?.() || false);
    return true;
  }

  function stopMicrophone() {
    state.micActive = false;
    if (state.worklet) {
      try {
        state.worklet.port.onmessage = null;
        state.worklet.disconnect();
      } catch (_) {}
      state.worklet = null;
    }
    if (state.silentGain) {
      try {
        state.silentGain.disconnect();
      } catch (_) {}
      state.silentGain = null;
    }
    if (state.source) {
      try {
        state.source.disconnect();
      } catch (_) {}
      state.source = null;
    }
    if (state.stream) {
      for (const t of state.stream.getTracks()) t.stop();
      state.stream = null;
    }
    state.captureSettings = null;
  }

  function disconnect() {
    state.intentionalClose = true;
    state.wantSession = false;
    clearReconnectTimer();
    state.reconnectAttempt = 0;
    if (state.pendingHello) {
      state.pendingHello.reject(new Error("WebSocket disconnected"));
      state.pendingHello = null;
    }
    stopMicrophone();
    unbindPlaybackReporter();
    const sessionId = state.sessionId;
    window.mayaBrowserAudioOutput?.endSession?.(sessionId);
    state.sessionId = null;
    state.connectionId = null;
    if (state.ws) {
      try {
        state.ws.close();
      } catch (_) {}
      state.ws = null;
    }
    state.connected = false;
    state.negotiated = false;
    state.micActive = false;
  }

  function interrupt() {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({ type: "interrupt" }));
    }
    window.mayaBrowserAudioOutput?.stop?.();
    window.mayaBrowserAudioOutput?.unduck?.();
  }

  window.mayaBrowserMic = {
    connect,
    startMicrophone,
    stopMicrophone,
    disconnect,
    interrupt,
    sendControl,
    packPcmFrame,
    getBackpressureStats() {
      return {
        clientDrops: state.clientDrops,
        wsBlocked: state.wsBlocked,
        bufferedAmount: state.ws ? state.ws.bufferedAmount || 0 : 0,
        sequence: state.sequence,
        sampleIndex: state.sampleIndex,
      };
    },
    getCaptureSettings() {
      return state.captureSettings ? { ...state.captureSettings } : null;
    },
    usesAudioWorklet() {
      return true;
    },
    onBecameLeader() {
      if (!state.wantSession) return;
      startMicrophone({ wsUrl: state.wsPath, gain: state.gain }).catch(() => {});
    },
    onLostLeadership() {
      // Keep wantSession so a later leadership win can reclaim the mic.
      const keepWant = state.wantSession;
      state.intentionalClose = true;
      clearReconnectTimer();
      if (state.pendingHello) {
        state.pendingHello.reject(new Error("voice leadership lost"));
        state.pendingHello = null;
      }
      stopMicrophone();
      unbindPlaybackReporter();
      const oldWs = state.ws;
      state.ws = null;
      if (oldWs) {
        try {
          oldWs.close();
        } catch (_) {}
      }
      state.connected = false;
      state.negotiated = false;
      state.connectionId = null;
      state.micActive = false;
      state.intentionalClose = false;
      state.wantSession = keepWant;
    },
    isActive() {
      return !!(
        state.micActive &&
        state.connected &&
        state.negotiated &&
        state.ws &&
        state.ws.readyState === WebSocket.OPEN
      );
    },
    isConnected() {
      return !!(
        state.connected &&
        state.negotiated &&
        state.ws &&
        state.ws.readyState === WebSocket.OPEN
      );
    },
  };

  // Best-effort unload signal — never relied on for lease correctness (server grace).
  window.addEventListener(
    "pagehide",
    () => {
      state.intentionalClose = true;
      state.wantSession = false;
      clearReconnectTimer();
      if (state.ws) {
        try {
          state.ws.close();
        } catch (_) {}
      }
    },
    { capture: true },
  );
})();
