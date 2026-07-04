/** Conversation state — shared across dashboard pages + sessionStorage (per operator). */
let _messageIdSeq = 0;

const _IDB_NAME = "maya-tts";
const _IDB_STORE = "audio";
const _IDB_VERSION = 1;

function _storageKey() {
  const uid = window._mayaCurrentUser?.id || "anonymous";
  return `maya.conversation.v1.${uid}`;
}

function _detailedStorageKey() {
  const uid = window._mayaCurrentUser?.id || "anonymous";
  return `maya.conversation.detailed.v1.${uid}`;
}

function _sidebarStorageKey() {
  const uid = window._mayaCurrentUser?.id || "anonymous";
  return `maya.conversation.sidebar.v1.${uid}`;
}

const IMMERSIVE_AVATAR_EVENT = "maya:toggle-immersive-avatar";

function _formatDuration(ms) {
  if (ms == null || ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function _formatSentAt(ts) {
  try {
    return new Date(ts).toLocaleTimeString([], {
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch (_) {
    return "";
  }
}

/** Drop leading VOICE: delivery cues from displayed / TTS replay text. */
function _stripVoiceDeliveryFromText(text) {
  let remaining = String(text || "").trimStart();
  const inlineRe = /(?<=[a-z,])\s+(?=[A-Z])/;

  while (remaining) {
    const probe = remaining.trimStart();
    const md = probe.match(/^\s*(?:[*_#\s])*/);
    const rest = probe.slice(md ? md[0].length : 0);
    if (!/^voice:/i.test(rest)) break;
    const afterVoice = rest.replace(/^voice:\s*/i, "");
    const nl = afterVoice.indexOf("\n");
    const inline = inlineRe.exec(afterVoice);
    let reply = "";
    if (nl !== -1 && (inline === null || nl <= inline.index)) {
      reply = afterVoice.slice(nl + 1).replace(/^\n+/, "");
    } else if (inline) {
      reply = afterVoice.slice(inline.index + inline[0].length);
    }
    remaining = reply.trimStart();
  }
  return remaining;
}

function _sanitizeMayaTurnText(text) {
  return _stripVoiceDeliveryFromText(text);
}

function _sanitizeStoredTurns(turns) {
  if (!Array.isArray(turns)) return;
  for (const t of turns) {
    if (t?.role === "maya" && t.text) t.text = _sanitizeMayaTurnText(t.text);
  }
}

function _lastMayaTurnIdx(store) {
  for (let i = store.turns.length - 1; i >= 0; i--) {
    if (store.turns[i]?.role === "maya") return i;
  }
  return -1;
}

function _endStreaming(store) {
  const last = store.turns[store.turns.length - 1];
  if (last?._streaming) {
    last._streaming = false;
    if (last.role === "maya" && last.text) {
      last.text = _sanitizeMayaTurnText(last.text);
    }
  }
}

function _finalizeChatMs(store) {
  if (!store._chatPendingAt) return;
  const idx = _lastMayaTurnIdx(store);
  if (idx < 0) return;
  const turn = store.turns[idx];
  if (!turn || turn.role !== "maya" || turn.chatMs != null) return;
  turn.chatMs = Date.now() - store._chatPendingAt;
  store._chatPendingAt = null;
}

function _applyPendingTurnMeta(store, turn) {
  if (!turn || turn.role !== "maya") return;
  if (!turn.deliveryCue && store._pendingDeliveryCue) {
    turn.deliveryCue = store._pendingDeliveryCue;
    store._pendingDeliveryCue = null;
  }
  if (!turn.ttsModel && store._pendingTtsModel) {
    turn.ttsModel = store._pendingTtsModel;
    store._pendingTtsModel = null;
  }
}

function _onDeliveryCue(store, cue) {
  const text = String(cue || "").trim();
  if (!text || store._ttsPreviewOnly) return;
  const idx = store._ttsTargetIdx ?? _lastMayaTurnIdx(store);
  if (idx < 0) {
    store._pendingDeliveryCue = text;
    return;
  }
  const turn = store.turns[idx];
  if (!turn || turn.role !== "maya") return;
  if (!turn.deliveryCue) turn.deliveryCue = text;
}

function _onTtsInfo(store, ev) {
  if (store._ttsPreviewOnly || !ev?.model) return;
  const model = String(ev.model);
  const idx = store._ttsTargetIdx ?? _lastMayaTurnIdx(store);
  if (idx < 0) {
    store._pendingTtsModel = model;
    return;
  }
  const turn = store.turns[idx];
  if (!turn || turn.role !== "maya") return;
  if (!turn.ttsModel) turn.ttsModel = model;
}

function _onTtsStart(store) {
  if (store._ttsPreviewOnly) return;
  const idx = store._ttsTargetIdx ?? _lastMayaTurnIdx(store);
  if (idx < 0) return;
  const turn = store.turns[idx];
  if (!turn || turn.role !== "maya") return;
  if (turn.ttsMs != null || store._ttsPendingAt != null) return;
  store._ttsPendingAt = Date.now();
  store._ttsPendingIdx = idx;
}

function _clearPlayingTurn(_store) {
  /* live session highlight — bubble replay uses per-turn audioPlaying */
}

function _onFirstAudio(store) {
  if (store._ttsPreviewOnly || store._ttsPendingAt == null || store._ttsPendingIdx == null) return;
  const turn = store.turns[store._ttsPendingIdx];
  if (!turn || turn.ttsMs != null) return;
  turn.ttsMs = Date.now() - store._ttsPendingAt;
  store._ttsPendingAt = null;
  store._ttsPendingIdx = null;
  store._ttsTargetIdx = null;
}

function _evCorrId(ev) {
  return ev?.corr_id || ev?.turn_id || null;
}

/** True only for server-minted ids (c_… / m_…), not local placeholders. */
function _isServerId(id) {
  return /^[cm]_/.test(String(id || ""));
}

function _normalizeTurnFields(t) {
  if (!t) return;
  if (t.turnId && !t.messageId) t.messageId = t.turnId;
  if (t.turnGroupId && !t.corrId) t.corrId = t.turnGroupId;
  delete t.turnId;
  delete t.turnGroupId;
}

function _nextMessageId() {
  _messageIdSeq += 1;
  return `msg-${Date.now()}-${_messageIdSeq}`;
}

function _ensureMessageIds(turns) {
  if (!Array.isArray(turns)) return;
  for (const t of turns) {
    _normalizeTurnFields(t);
    if (t && !t.messageId) t.messageId = _nextMessageId();
  }
}

function _serializeTurns(turns) {
  return (turns || []).map((t) => {
    const copy = { ...t };
    delete copy.audioUrl;
    delete copy.audioPlaying;
    delete copy.audioBusy;
    delete copy.audioError;
    return copy;
  });
}

function _mergeServerTurns(localTurns, serverTurns) {
  const local = Array.isArray(localTurns) ? localTurns : [];
  const used = new Set();
  return (serverTurns || []).map((s) => {
    const sid = s.message_id;
    const corrId = s.corr_id || s.turn_id || null;
    if (sid) {
      const idx = local.findIndex((l, i) => !used.has(i) && l.messageId === sid);
      if (idx >= 0) {
        used.add(idx);
        const l = local[idx];
        return {
          ...l,
          role: s.role,
          text: s.role === "maya" ? _sanitizeMayaTurnText(s.text) : s.text,
          messageId: sid,
          corrId: corrId || l.corrId,
          completionId: s.completion_id || l.completionId,
        };
      }
    }
    for (let i = 0; i < local.length; i++) {
      if (used.has(i)) continue;
      const l = local[i];
      if (l.role === s.role && (l.text || "") === (s.text || "")) {
        used.add(i);
        return {
          ...l,
          role: s.role,
          text: s.role === "maya" ? _sanitizeMayaTurnText(s.text) : s.text,
          messageId: s.message_id || l.messageId,
          corrId: corrId || l.corrId,
          completionId: s.completion_id || l.completionId,
        };
      }
    }
    return {
      messageId: s.message_id || _nextMessageId(),
      corrId,
      completionId: s.completion_id || null,
      role: s.role,
      text: s.role === "maya" ? _sanitizeMayaTurnText(s.text) : s.text,
    };
  });
}

function _attachCompletionMeta(store, ev) {
  if (!ev?.message_id) return;
  const turn = store.turns.find((t) => t.messageId === ev.message_id);
  if (!turn) return;
  if (ev.completion_id) turn.completionId = ev.completion_id;
  const corrId = _evCorrId(ev);
  if (corrId && !turn.corrId) turn.corrId = corrId;
}

async function _idbOpen() {
  return new Promise((resolve, reject) => {
    if (!window.indexedDB) {
      reject(new Error("indexedDB unavailable"));
      return;
    }
    const req = indexedDB.open(_IDB_NAME, _IDB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(_IDB_STORE)) {
        db.createObjectStore(_IDB_STORE);
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function _idbGetAudio(hash) {
  if (!hash) return null;
  try {
    const db = await _idbOpen();
    return new Promise((resolve) => {
      const tx = db.transaction(_IDB_STORE, "readonly");
      const req = tx.objectStore(_IDB_STORE).get(hash);
      req.onsuccess = () => {
        db.close();
        resolve(req.result || null);
      };
      req.onerror = () => {
        db.close();
        resolve(null);
      };
    });
  } catch (_) {
    return null;
  }
}

async function _idbPutAudio(hash, blob, ms) {
  if (!hash || !blob) return false;
  try {
    const db = await _idbOpen();
    return new Promise((resolve) => {
      const tx = db.transaction(_IDB_STORE, "readwrite");
      tx.objectStore(_IDB_STORE).put({ blob, ms, createdAt: Date.now() }, hash);
      tx.oncomplete = () => {
        db.close();
        resolve(true);
      };
      tx.onerror = () => {
        db.close();
        resolve(false);
      };
    });
  } catch (_) {
    return false;
  }
}

async function _hydrateTurnAudio(turn) {
  if (!turn || turn.role !== "maya" || turn.audioUrl || !turn.audioHash) return false;
  const rec = await _idbGetAudio(turn.audioHash);
  if (!rec?.blob) return false;
  turn.audioUrl = URL.createObjectURL(rec.blob);
  if (rec.ms != null) turn.ttsMs = rec.ms;
  turn.ttsCached = true;
  return true;
}

function _hdrInt(headers, name) {
  const v = headers.get(name);
  if (v == null || v === "") return null;
  const n = parseInt(v, 10);
  return Number.isFinite(n) ? n : null;
}

function _ttsTimingFromHeaders(headers) {
  return {
    ttfaMs: _hdrInt(headers, "X-TTS-TTFA-Ms"),
    synthMs: _hdrInt(headers, "X-TTS-Synth-Ms"),
    encodeMs: _hdrInt(headers, "X-TTS-Encode-Ms"),
    totalMs: _hdrInt(headers, "X-TTS-Total-Ms"),
    lockWaitMs: _hdrInt(headers, "X-TTS-Lock-Wait-Ms"),
  };
}

function _concatU8(a, b) {
  if (!a.length) return b;
  const out = new Uint8Array(a.length + b.length);
  out.set(a);
  out.set(b, a.length);
  return out;
}

function _encodeWavPcm16(pcm16, sr) {
  const dataBytes = pcm16.length * 2;
  const buf = new ArrayBuffer(44 + dataBytes);
  const view = new DataView(buf);
  const writeStr = (off, s) => {
    for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i));
  };
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + dataBytes, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sr, true);
  view.setUint32(28, sr * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, "data");
  view.setUint32(40, dataBytes, true);
  let o = 44;
  for (let i = 0; i < pcm16.length; i++, o += 2) view.setInt16(o, pcm16[i], true);
  return buf;
}

function _pcmChunksToWavBlob(chunks, sr) {
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const pcm16 = new Int16Array(total);
  let off = 0;
  for (const chunk of chunks) {
    for (let i = 0; i < chunk.length; i++) {
      const s = Math.max(-1, Math.min(1, chunk[i]));
      pcm16[off++] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
  }
  return new Blob([_encodeWavPcm16(pcm16, sr)], { type: "audio/wav" });
}

async function _consumeTtsStream(response, { streamPlay = false } = {}) {
  const t0 = performance.now();
  const ct = response.headers.get("Content-Type") || "";
  if (ct.includes("audio/wav")) {
    const blob = await response.blob();
    const hash = response.headers.get("X-TTS-Hash") || "";
    const serverCache = response.headers.get("X-TTS-Cache") || "";
    const serverTiming = _ttsTimingFromHeaders(response.headers);
    return {
      ok: true,
      url: URL.createObjectURL(blob),
      ms: Math.round(performance.now() - t0),
      ttfaMs: serverTiming.ttfaMs,
      serverTiming,
      hash,
      serverCache,
      blob,
      streamed: false,
    };
  }

  if (!response.body) {
    return { ok: false, ms: Math.round(performance.now() - t0), error: "Empty TTS stream" };
  }

  const reader = response.body.getReader();
  let buf = new Uint8Array(0);
  let meta = null;
  let ttfaMs = null;
  let doneTiming = null;
  const pcmParts = [];
  let sr = 24000;
  const schedule = streamPlay ? window.mayaBrowserAudioOutput?.scheduleChunk : null;
  if (schedule) {
    window.mayaBrowserAudioOutput?.resumeOutput?.();
    await window.mayaBrowserAudioOutput?.resume?.();
  }

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf = _concatU8(buf, value);
    while (buf.length >= 4) {
      const len = new DataView(buf.buffer, buf.byteOffset, 4).getUint32(0, true);
      if (buf.length < 4 + len) break;
      const frame = buf.slice(4, 4 + len);
      buf = buf.slice(4 + len);
      if (!meta) {
        meta = JSON.parse(new TextDecoder().decode(frame));
        sr = meta.sr || 24000;
        continue;
      }
      let ctrl = null;
      try {
        ctrl = JSON.parse(new TextDecoder().decode(frame));
      } catch (_) {
        ctrl = null;
      }
      if (ctrl?.type === "done") {
        doneTiming = ctrl;
        continue;
      }
      if (ctrl?.type === "error") {
        return {
          ok: false,
          ms: Math.round(performance.now() - t0),
          error: ctrl.error || "TTS stream failed",
        };
      }
      const pcm = new Float32Array(frame.buffer, frame.byteOffset, frame.byteLength / 4);
      if (ttfaMs == null) ttfaMs = Math.round(performance.now() - t0);
      pcmParts.push(pcm);
      if (schedule) await schedule(pcm, sr);
    }
  }

  if (!pcmParts.length) {
    return { ok: false, ms: Math.round(performance.now() - t0), error: "TTS produced no audio" };
  }

  const blob = _pcmChunksToWavBlob(pcmParts, sr);
  const serverTiming = {
    ttfaMs: doneTiming?.ttfa_ms != null ? Math.round(doneTiming.ttfa_ms) : ttfaMs,
    synthMs: doneTiming?.synth_ms != null ? Math.round(doneTiming.synth_ms) : null,
    encodeMs: doneTiming?.encode_ms != null ? Math.round(doneTiming.encode_ms) : null,
    totalMs: doneTiming?.total_ms != null ? Math.round(doneTiming.total_ms) : null,
    lockWaitMs: doneTiming?.lock_wait_ms != null ? Math.round(doneTiming.lock_wait_ms) : null,
  };
  return {
    ok: true,
    url: URL.createObjectURL(blob),
    ms: Math.round(performance.now() - t0),
    ttfaMs: serverTiming.ttfaMs ?? ttfaMs,
    serverTiming,
    hash: meta?.hash || "",
    serverCache: "miss",
    blob,
    streamed: true,
  };
}

async function _fetchTtsBlob(text, instruct, { streamPlay = false } = {}) {
  const body = { text };
  if (instruct) body.instruct = instruct;
  const t0 = performance.now();
  let r;
  try {
    r = await fetch("/api/voice/agent/tts/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (e) {
    return { ok: false, ms: Math.round(performance.now() - t0), error: String(e.message || e) };
  }
  if (!r.ok) {
    let data = {};
    try {
      data = await r.json();
    } catch (_) {
      data = {};
    }
    return {
      ok: false,
      ms: Math.round(performance.now() - t0),
      error:
        data.error ||
        data.detail ||
        (r.status === 404
          ? "TTS stream API not found — restart launch.py to load the new route."
          : `Speak failed (HTTP ${r.status})`),
    };
  }
  const result = await _consumeTtsStream(r, { streamPlay });
  if (!result.ok) return result;
  return result;
}

function _persistConversation(store) {
  try {
    sessionStorage.setItem(
      _storageKey(),
      JSON.stringify({
        turns: _serializeTurns(store.turns),
        statusLabel: store.statusLabel,
        step: store.step,
      }),
    );
  } catch (_) {}
}

function _restoreConversation(store) {
  try {
    const raw = sessionStorage.getItem(_storageKey());
    if (!raw) return;
    const data = JSON.parse(raw);
    if (Array.isArray(data.turns)) {
      store.turns = data.turns;
      _ensureMessageIds(store.turns);
      _sanitizeStoredTurns(store.turns);
      _persistConversation(store);
    }
    if (data.statusLabel) store.statusLabel = data.statusLabel;
    if (data.step) store.step = data.step;
  } catch (_) {}
}

function _scrollTranscript(smooth = true) {
  requestAnimationFrame(() => {
    const el = document.querySelector(".md-log");
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  });
}

function _applyAgentEvent(store, ev) {
  if (!ev || !ev.type) return;
  if (ev.type === "delivery" && ev.cue) {
    _onDeliveryCue(store, ev.cue);
    _persistConversation(store);
    return;
  }
  if (ev.type === "tts_info" && ev.model) {
    _onTtsInfo(store, ev);
    _persistConversation(store);
    return;
  }
  if (ev.type === "status") {
    const v = ev.value || "idle";
    store.statusLabel = v;
    if (v === "listening" || v === "hearing") {
      store.step = "listen";
      _endStreaming(store);
      _finalizeChatMs(store);
      if (!store._ttsPreviewOnly) {
        _clearPlayingTurn(store);
        store.stopTurnAudio?.();
      }
      if (store.ttsBusy) {
        store.ttsBusy = false;
        store._ttsPreviewOnly = false;
      }
      _attachCompletionMeta(store, ev);
    } else if (v === "transcribing") store.step = "detect";
    else if (v === "thinking") {
      store.step = "reason";
      store._expectingReply = true;
    } else if (v === "speaking") {
      store.step = "maya";
      _endStreaming(store);
      _finalizeChatMs(store);
      _onTtsStart(store);
      store._expectingReply = true;
    } else if (v === "idle") {
      _endStreaming(store);
      _finalizeChatMs(store);
      store._expectingReply = false;
      if (!store._ttsPreviewOnly) {
        _clearPlayingTurn(store);
        store.stopTurnAudio?.();
      }
      if (store.ttsBusy) {
        store.ttsBusy = false;
        store._ttsPreviewOnly = false;
      }
      _attachCompletionMeta(store, ev);
    }
    _persistConversation(store);
    return;
  }
  if (ev.type === "audio_stop") {
    if (!store._ttsPreviewOnly) {
      _clearPlayingTurn(store);
      store.stopTurnAudio?.();
    }
    return;
  }
  if (ev.type === "audio" && ev.data) {
    _onFirstAudio(store);
    _persistConversation(store);
    return;
  }
  if (ev.type === "error" && ev.text && store.ttsBusy) {
    store.ttsError = ev.text;
    store.ttsBusy = false;
    store._ttsPreviewOnly = false;
    return;
  }
  if (ev.type === "tts_error" && ev.text) {
    store.ttsError = ev.text;
    store.ttsBusy = false;
    store._ttsPreviewOnly = false;
    return;
  }
  if (ev.type === "user" && ev.text) {
    const last = store.turns[store.turns.length - 1];
    if (last && last.role === "operator" && last.text === ev.text) return;
    store.turns.push({
      messageId: ev.message_id || _nextMessageId(),
      corrId: _evCorrId(ev),
      role: "operator",
      text: ev.text,
      sentAt: Date.now(),
    });
    store._chatPendingAt = Date.now();
    store._ttsPendingAt = null;
    store._ttsPendingIdx = null;
    store._ttsTargetIdx = null;
    _persistConversation(store);
    _scrollTranscript();
    return;
  }
  if (ev.type === "ai" && ev.text) {
    const last = store.turns[store.turns.length - 1];
    const chunk = String(ev.text);
    const streamingMaya = last && last.role === "maya" && last._streaming;
    if (last && last.role === "maya" && !last._streaming && chunk.trim() === (last.text || "").trim()) {
      return;
    }
    if (!streamingMaya && !store._expectingReply) return;
    if (streamingMaya) {
      if (ev.message_id) last.messageId = ev.message_id;
      const corrId = _evCorrId(ev);
      if (corrId) last.corrId = corrId;
      const cur = last.text || "";
      if (!chunk || cur.endsWith(chunk)) return;
      if (cur && chunk.startsWith(cur)) {
        last.text = chunk;
        _applyPendingTurnMeta(store, last);
        _persistConversation(store);
        _scrollTranscript();
        return;
      }
      last.text = cur + chunk;
      _applyPendingTurnMeta(store, last);
    } else {
      store.turns.push({
        messageId: ev.message_id || _nextMessageId(),
        corrId: _evCorrId(ev),
        role: "maya",
        text: chunk,
        _streaming: true,
      });
      _applyPendingTurnMeta(store, store.turns[store.turns.length - 1]);
    }
    _persistConversation(store);
    _scrollTranscript();
  }
}

document.addEventListener("alpine:init", () => {
  Alpine.store("mayaConversation", {
    sessionOn: false,
    statusLabel: "idle",
    step: "listen",
    draft: "",
    ttsDraft: "Haha! That was ridiculous.",
    ttsInstruct: "",
    ttsBusy: false,
    ttsError: "",
    turns: [],
    useWebLLM: false,
    sending: false,
    detailed: false,
    sidebarOpen: true,
    _expectingReply: false,
    _activeTurnAudio: null,
    _activeTurnMessageId: null,
    _hydrated: false,
    _basicChatNoted: false,
    _chatPendingAt: null,
    _ttsPendingAt: null,
    _ttsPendingIdx: null,
    _ttsTargetIdx: null,
    _ttsPreviewOnly: false,
    _pendingTtsModel: null,
    _pendingDeliveryCue: null,

    persist() {
      _persistConversation(this);
    },

    persistDetailed() {
      try {
        sessionStorage.setItem(_detailedStorageKey(), this.detailed ? "1" : "0");
      } catch (_) {}
    },

    persistSidebar() {
      try {
        sessionStorage.setItem(_sidebarStorageKey(), this.sidebarOpen ? "1" : "0");
      } catch (_) {}
    },

    toggleSidebar() {
      this.sidebarOpen = !this.sidebarOpen;
      this.persistSidebar();
      if (this.sidebarOpen) {
        setTimeout(() => window.dispatchEvent(new Event("resize")), 60);
      }
    },

    toggleImmersiveAvatar() {
      try {
        window.dispatchEvent(new CustomEvent(IMMERSIVE_AVATAR_EVENT));
      } catch (_) {}
    },

    restore() {
      _restoreConversation(this);
      try {
        this.detailed = sessionStorage.getItem(_detailedStorageKey()) === "1";
      } catch (_) {}
      try {
        const stored = sessionStorage.getItem(_sidebarStorageKey());
        if (stored !== null) this.sidebarOpen = stored === "1";
      } catch (_) {}
    },

    formatSentAt(ts) {
      return _formatSentAt(ts);
    },

    operatorMetaParts(turn) {
      const parts = [];
      if (turn.sentAt) parts.push({ text: `sent ${_formatSentAt(turn.sentAt)}` });
      if (turn.corrId) parts.push({ text: turn.corrId, dim: !_isServerId(turn.corrId) });
      if (turn.messageId) parts.push({ text: turn.messageId, dim: !_isServerId(turn.messageId) });
      return parts;
    },

    mayaMetaParts(turn) {
      const parts = [];
      if (turn.deliveryCue) parts.push({ text: `Maya · ${turn.deliveryCue}` });
      if (turn.corrId) parts.push({ text: turn.corrId, dim: !_isServerId(turn.corrId) });
      if (turn.chatMs != null) parts.push({ text: `chat ${_formatDuration(turn.chatMs)}` });
      const tts = turn.ttsMs != null ? _formatDuration(turn.ttsMs) : "—";
      let ttsPart = `TTS ${tts}`;
      if (turn.ttsTtfaMs != null) ttsPart += ` (ttfa ${_formatDuration(turn.ttsTtfaMs)})`;
      if ((turn.ttsCached || turn.ttsReplay) && turn.ttsMs != null) ttsPart += " (cached)";
      if (turn.ttsModel) parts.push({ text: ttsPart + ` · ${turn.ttsModel}` });
      else parts.push({ text: ttsPart });
      if (turn.messageId) parts.push({ text: turn.messageId, dim: !_isServerId(turn.messageId) });
      if (turn.completionId) parts.push({ text: `cmpl ${turn.completionId}` });
      return parts;
    },

    formatOperatorMeta(turn) {
      return this.operatorMetaParts(turn).map((p) => p.text).join(" · ");
    },

    formatMayaMeta(turn) {
      return this.mayaMetaParts(turn).map((p) => p.text).join(" · ");
    },

    stacksWithPrev(turn, index) {
      if (!this.detailed || !turn?.corrId || index <= 0) return false;
      const prev = this.turns[index - 1];
      return prev?.corrId === turn.corrId;
    },

    handleAgentEvent(ev) {
      _applyAgentEvent(this, ev);
    },

    async syncFromServer() {
      try {
        const [statusR, convR] = await Promise.all([
          fetch("/api/voice/agent/status"),
          fetch("/api/voice/agent/conversation"),
        ]);
        if (statusR.ok) {
          const d = await statusR.json();
          this.sessionOn = !!d.session_running;
          if (d.status) this.statusLabel = d.status;
        }
        if (convR.ok) {
          const d = await convR.json();
          if (d.session_running !== undefined) this.sessionOn = !!d.session_running;
          if (d.status) this.statusLabel = d.status;
          if (Array.isArray(d.turns) && d.turns.length > this.turns.length) {
            this.turns = _mergeServerTurns(this.turns, d.turns);
            _scrollTranscript();
          }
        }
        this.persist();
      } catch (_) {}
    },

    async ensureHydrated() {
      if (this._hydrated) return;
      this.restore();
      await this.rehydrateAudio();
      await this.loadSettings();
      await this.syncFromServer();
      this._hydrated = true;
    },

    async rehydrateAudio() {
      for (const t of this.turns) {
        await _hydrateTurnAudio(t);
      }
    },

    async loadSettings() {
      try {
        const r = await fetch("/api/voice/settings");
        if (r.ok) {
          const data = await r.json();
          this.useWebLLM = data.settings?.reasoning?.provider === "webllm";
        }
      } catch (_) {}
    },

    async startSession() {
      const r = await fetch("/api/voice/agent/start", { method: "POST" });
      const data = await r.json();
      if (data.ok) {
        this.sessionOn = true;
        window.dispatchEvent(new CustomEvent("maya-session-start"));
      } else if (data.error === "voice_in_use") {
        const who = data.owner?.speaker_name || data.owner?.context_id || "another user";
        this.turns.push({ messageId: _nextMessageId(), role: "system", text: `Voice is in use by ${who}. Try again when they finish.` });
        this.persist();
        _scrollTranscript();
      } else {
        this.turns.push({ messageId: _nextMessageId(), role: "system", text: data.error || "Could not start session" });
        this.persist();
        _scrollTranscript();
      }
    },

    async stopSession() {
      await fetch("/api/voice/agent/stop", { method: "POST" });
      this.sessionOn = false;
      window.dispatchEvent(new CustomEvent("maya-session-stop"));
      this.persist();
    },

    stopTurnAudio() {
      if (this._activeTurnAudio) {
        this._activeTurnAudio.pause();
        this._activeTurnAudio = null;
        this._activeTurnMessageId = null;
      }
      for (const t of this.turns) {
        if (t.audioPlaying) t.audioPlaying = false;
      }
    },

    async playTurnAudio(turn) {
      if (!turn || turn.role !== "maya" || turn._streaming || turn.audioBusy) return;
      const text = (turn.text || "").trim();
      if (!text) return;
      if (!Alpine.store("mayaShell")?.ready) {
        turn.audioError = "Agent not ready";
        return;
      }

      if (turn.audioPlaying && this._activeTurnMessageId === turn.messageId && this._activeTurnAudio) {
        this._activeTurnAudio.pause();
        turn.audioPlaying = false;
        this._activeTurnAudio = null;
        this._activeTurnMessageId = null;
        return;
      }

      this.stopTurnAudio();
      turn.audioError = "";

      try {
        if (!turn.audioUrl) {
          await _hydrateTurnAudio(turn);
        }
        if (!turn.audioUrl) {
          turn.audioBusy = true;
          const result = await _fetchTtsBlob(text, undefined, { streamPlay: true });
          turn.audioBusy = false;
          if (!result.ok) {
            turn.audioError = result.error;
            return;
          }
          turn.audioUrl = result.url;
          turn.ttsMs = result.ms;
          turn.ttsTtfaMs = result.ttfaMs ?? null;
          turn.audioHash = result.hash || turn.audioHash;
          turn.ttsCached = result.serverCache === "hit";
          if (result.hash && result.blob) {
            await _idbPutAudio(result.hash, result.blob, result.ms);
          }
          this.persist();
          if (result.streamed) {
            turn.audioPlaying = true;
            const waitMs = Math.max(500, (result.ms || 0) + 200);
            await new Promise((resolve) => setTimeout(resolve, waitMs));
            turn.audioPlaying = false;
            return;
          }
        } else {
          turn.ttsCached = true;
        }

        window.mayaBrowserAudioOutput?.resumeOutput?.();
        window.mayaBrowserAudioOutput?.resume?.();
        const audio = new Audio(turn.audioUrl);
        this._activeTurnAudio = audio;
        this._activeTurnMessageId = turn.messageId;
        turn.audioPlaying = true;

        audio.onended = () => {
          turn.audioPlaying = false;
          if (this._activeTurnMessageId === turn.messageId) {
            this._activeTurnAudio = null;
            this._activeTurnMessageId = null;
          }
        };
        audio.onerror = () => {
          turn.audioPlaying = false;
          turn.audioError = "Could not play audio in browser";
          if (this._activeTurnMessageId === turn.messageId) {
            this._activeTurnAudio = null;
            this._activeTurnMessageId = null;
          }
        };
        await audio.play();
      } catch (e) {
        turn.audioBusy = false;
        turn.audioPlaying = false;
        turn.audioError = String(e.message || e);
      }
    },

    async speakPreview() {
      const text = this.ttsDraft.trim();
      if (!text || this.ttsBusy || !Alpine.store("mayaShell")?.ready) return;
      this.stopTurnAudio();
      window.mayaBrowserAudioOutput?.resume?.();
      this.ttsBusy = true;
      this.ttsError = "";
      this._ttsPreviewOnly = true;
      this.step = "maya";
      try {
        const instruct = this.ttsInstruct.trim() || undefined;
        const result = await _fetchTtsBlob(text, instruct, { streamPlay: true });
        if (!result.ok) {
          this.ttsError = result.error;
          this.ttsBusy = false;
          this._ttsPreviewOnly = false;
          this.step = "listen";
          return;
        }
        if (result.streamed) {
          this.ttsBusy = false;
          this._ttsPreviewOnly = false;
          this.step = "listen";
          return;
        }
        const url = result.url;
        const audio = new Audio(url);
        audio.onended = () => {
          URL.revokeObjectURL(url);
          this.ttsBusy = false;
          this._ttsPreviewOnly = false;
          this.step = "listen";
        };
        audio.onerror = () => {
          URL.revokeObjectURL(url);
          this.ttsError = "Could not play audio in browser";
          this.ttsBusy = false;
          this.step = "listen";
        };
        await audio.play();
      } catch (e) {
        this.ttsError = String(e.message || e);
        this.ttsBusy = false;
        this._ttsPreviewOnly = false;
        this.step = "listen";
      }
    },

    onTtsKeydown(e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this.speakPreview();
      }
    },

    async sendServer() {
      const text = this.draft.trim();
      if (!text || this.sending) return;
      const shell = Alpine.store("mayaShell");
      const caps = shell?.capabilities || {};
      const textChat = caps.text_chat === true || shell?.llmReady === true;
      this.sending = true;
      this.draft = "";
      this.step = "reason";
      this._chatPendingAt = Date.now();
      try {
        if (!textChat) {
          this.turns.push({ messageId: _nextMessageId(), role: "operator", text, sentAt: Date.now() });
          const detail =
            shell?.llmHealth?.detail ||
            shell?.llmError ||
            "LLM unavailable — check Settings → Reasoning.";
          this.turns.push({ messageId: _nextMessageId(), role: "system", text: detail });
          this.persist();
          _scrollTranscript();
          return;
        }
        if (!caps.text_chat_enriched && !this._basicChatNoted) {
          this._basicChatNoted = true;
          this.turns.push({
            messageId: _nextMessageId(),
            role: "system",
            text: "Basic LLM replies — full agent (personality, memory, voice) still loading.",
          });
        }
        const r = await fetch("/api/voice/agent/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
        const data = await r.json();
        if (!data.ok) {
          this.turns.push({ messageId: _nextMessageId(), role: "system", text: data.error || "Chat failed" });
          this.persist();
          _scrollTranscript();
        }
      } finally {
        this.sending = false;
        this.step = "listen";
      }
    },

    onKeydown(e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this.sendServer();
      }
    },

    reset() {
      this.stopTurnAudio();
      for (const t of this.turns) {
        if (t.audioUrl) URL.revokeObjectURL(t.audioUrl);
      }
      this.turns = [];
      this._chatPendingAt = null;
      this._ttsPendingAt = null;
      this._ttsPendingIdx = null;
      this._ttsTargetIdx = null;
      this._expectingReply = false;
      this.persist();
      _scrollTranscript(false);
    },
  });

  Alpine.data("mayaConversation", () => ({
    get agentReady() {
      return Alpine.store("mayaShell")?.ready || false;
    },
    get agentError() {
      return Alpine.store("mayaShell")?.error || "";
    },
    get llmOk() {
      const shell = Alpine.store("mayaShell");
      return !!(shell?.llmReady || shell?.llmOk);
    },
    get textChatReady() {
      const shell = Alpine.store("mayaShell");
      return shell?.capabilities?.text_chat === true || shell?.llmReady === true;
    },
    get enrichedChatReady() {
      return Alpine.store("mayaShell")?.capabilities?.text_chat_enriched === true;
    },
    get llmError() {
      return Alpine.store("mayaShell")?.llmError || "";
    },
    get webllmFailed() {
      const st = Alpine.store("mayaShell")?.webllmBridgeStatus || "";
      if (/failed|unavailable|rejected|null/i.test(st)) return st;
      const issue = window.mayaWebLLMBridge?.gpuIssue;
      return issue || "";
    },
    get webllmTroubleshoot() {
      return window.mayaWebLLMBridge?.troubleshoot || "";
    },

    init() {
      Alpine.store("mayaConversation").ensureHydrated().then(() => {
        _scrollTranscript(false);
      });
    },
  }));
});

// Expose for mayaShell (loads after this file on dashboard pages).
window.mayaConversationStore = {
  handleAgentEvent(ev) {
    const store = window.Alpine?.store("mayaConversation");
    if (store) store.handleAgentEvent(ev);
  },
  async ensureHydrated() {
    const store = window.Alpine?.store("mayaConversation");
    if (store) await store.ensureHydrated();
  },
  async syncFromServer() {
    const store = window.Alpine?.store("mayaConversation");
    if (store) await store.syncFromServer();
  },
};
