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

function _collapseDuplicateText(text) {
  const t = String(text || "").trim();
  if (t.length < 16) return t;
  const half = Math.floor(t.length / 2);
  if (t.slice(0, half) === t.slice(half)) return t.slice(0, half).trim();
  return t;
}

function _stripDialogueNamePrefix(text) {
  let body = String(text || "").trim();
  const re = /^(?:Maya(?:-sama)?|[A-Z][A-Za-z0-9_-]*(?:-sama)?)\s*:\s*/i;
  while (re.test(body)) body = body.replace(re, "").trim();
  return body;
}

function _stripWrappingQuotes(text) {
  let body = String(text || "").trim();
  if (body.length >= 2 && body[0] === body[body.length - 1] && (body[0] === '"' || body[0] === "'")) {
    const inner = body.slice(1, -1).trim();
    if (inner) return inner;
  }
  return body;
}

function _stripLlmArtifacts(text) {
  let body = String(text || "").trim();
  if (!body) return "";
  body = body.replace(/<\s*START\s*>/gi, " ");
  body = body.replace(
    /(?:play_avatar_animation|set_avatar_expression|list_avatar_animations|list_avatar_expressions)\s*\([^)]*\)/gi,
    " ",
  );
  return body.replace(/\s{2,}/g, " ").trim();
}

/** Drop VOICE: delivery cues from displayed / TTS replay text (anywhere in the message). */
function _stripVoiceDeliveryFromText(text) {
  let body = _stripLlmArtifacts(text);
  if (!body) return "";

  const embeddedLineRe = /(?:^|[\n\r]+)\s*(?:[*_#]\s*)*VOICE:\s*([^\n\r]+)/gi;
  const inlineRe = /VOICE:\s*([^A-Z\n\r]+?)\s+(?=[A-Z"'!])/gi;
  const actionRe = /\*[^*]+\*/g;

  body = body.replace(embeddedLineRe, " ");
  let match;
  while ((match = inlineRe.exec(body)) !== null) {
    body = `${body.slice(0, match.index)} ${body.slice(match.index + match[0].length)}`;
    inlineRe.lastIndex = 0;
  }
  const leadingCue = body.match(/^\s*\*([^*]{1,60}?)\*\s+(?=\S)/i);
  if (leadingCue && !/^(?:flips?|waves?|lands?|smirks?|dances?|spins?|jumps?)\b/i.test(leadingCue[1].trim())) {
    body = body.slice(leadingCue[0].length).trimStart();
  }
  body = body.replace(actionRe, " ");
  body = _collapseDuplicateText(body);
  body = _stripDialogueNamePrefix(body);
  body = _stripWrappingQuotes(body);
  return body.replace(/\s{2,}/g, " ").trim();
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

function _hasCmdPending(store) {
  return store.turns.some((t) => t.cmdPhase === "ack" && t._cmdPending);
}

function _finalizeChatMs(store) {
  if (!store._chatPendingAt) return;
  if (_hasCmdPending(store)) return;
  const idx = _lastMayaTurnIdx(store);
  if (idx < 0) return;
  const turn = store.turns[idx];
  if (!turn || turn.role !== "maya" || turn.chatMs != null) return;
  turn.chatMs = Date.now() - store._chatPendingAt;
  store._chatPendingAt = null;
}

function _applyImagineTurnMeta(turn, { traceId, jobId, artifacts, ev } = {}) {
  if (!turn || turn.role !== "maya") return;
  if (traceId) turn.traceId = traceId;
  if (jobId) turn.jobId = jobId;
  const img = (artifacts || []).find((a) => a?.type === "image");
  if (img) {
    if (img.job_id) turn.jobId = img.job_id;
    if (img.model) turn.imagineModel = img.model;
    if (img.model_key) turn.imagineModelKey = img.model_key;
    if (img.workflow_id) turn.workflowId = img.workflow_id;
    if (img.workflow_name) turn.workflowName = img.workflow_name;
    if (img.gen_ms != null) turn.genMs = img.gen_ms;
    if (img.user_id) turn.imagineUserId = img.user_id;
  }
  if (ev) {
    if (ev.model && !turn.imagineModel) turn.imagineModel = ev.model;
    if (ev.model_key && !turn.imagineModelKey) turn.imagineModelKey = ev.model_key;
    if (ev.workflow_id && !turn.workflowId) turn.workflowId = ev.workflow_id;
    if (ev.workflow_name && !turn.workflowName) turn.workflowName = ev.workflow_name;
    if (ev.gen_ms != null && turn.genMs == null) turn.genMs = ev.gen_ms;
    if (ev.user_id && !turn.imagineUserId) turn.imagineUserId = ev.user_id;
    if (ev.trace_id && !turn.traceId) turn.traceId = ev.trace_id;
    if (ev.job_id && !turn.jobId) turn.jobId = ev.job_id;
  }
}

function _imagineTurnBodyHidden(turn) {
  if (!turn?.artifacts?.length) return false;
  if (turn._remarkStreaming) return false;
  const body = String(turn.text || "").trim();
  if (!body) return true;
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(body)) return true;
  return /^image ready\.?$/i.test(body);
}

function _imagineRemarkHint(turn) {
  if (!turn?.artifacts?.length) return null;
  if (turn._remarkStreaming) return null;
  const body = String(turn.text || "").trim();
  if (!body || /^image ready\.?$/i.test(body)) {
    return { text: "remark skipped — check Settings → Imagine → Remark vision model", dim: true };
  }
  return null;
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

function _findMayaTurnForEvent(store, ev) {
  const mid = ev.message_id;
  const corr = _evCorrId(ev);
  if (mid) {
    const byId = store.turns.find((t) => t.role === "maya" && t.messageId === mid);
    if (byId) return byId;
  }
  if (corr) {
    for (let i = store.turns.length - 1; i >= 0; i--) {
      const t = store.turns[i];
      if (t?.role === "maya" && t.corrId === corr) return t;
    }
  }
  const last = store.turns[store.turns.length - 1];
  if (last?.role === "maya" && last._streaming) return last;
  return null;
}

function _mergeAiChunk(turn, chunk, { final = false } = {}) {
  const piece = String(chunk || "");
  if (!piece) return false;
  const cur = turn.text || "";
  if (final) {
    turn.text = _sanitizeMayaTurnText(piece);
    return true;
  }
  if (!turn._streaming) return false;
  if (piece === cur) return false;
  if (!cur) {
    turn.text = piece;
    return true;
  }
  if (cur.endsWith(piece)) return false;
  if (piece.startsWith(cur) || (piece.length > cur.length && piece.includes(cur))) {
    turn.text = piece;
    return true;
  }
  turn.text = cur + piece;
  return true;
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

function _findMayaTurnByCorr(store, corrId) {
  if (!corrId) return -1;
  for (let i = store.turns.length - 1; i >= 0; i--) {
    const t = store.turns[i];
    if (t?.role === "maya" && t.corrId === corrId) return i;
  }
  return -1;
}

function _findOperatorTurnByText(store, text) {
  for (let i = store.turns.length - 1; i >= 0; i--) {
    const t = store.turns[i];
    if (t?.role === "operator" && t.text === text) return i;
  }
  return -1;
}

function _hasCmdReply(store, corrId, text) {
  if (_findMayaTurnByCorr(store, corrId) >= 0) return true;
  const last = store.turns[store.turns.length - 1];
  if (last?.role === "maya" && text && last.text?.trim() === String(text).trim()) return true;
  return false;
}

function _markCmdFailed(store, corrId) {
  if (!corrId) return;
  const ackIdx = _findCmdAckTurn(store, corrId);
  const optimisticIdx = ackIdx >= 0
    ? ackIdx
    : store.turns.findIndex((t) => t._optimisticAck && t.cmdPhase === "ack" && t._cmdPending);
  if (optimisticIdx < 0) return;
  if (!store._cmdFailedCorrIds) store._cmdFailedCorrIds = {};
  store._cmdFailedCorrIds[corrId] = true;
}

function _isCmdFailed(store, corrId) {
  if (!corrId) return false;
  return !!store._cmdFailedCorrIds?.[corrId];
}

function _operatorTextBeforeTurn(store, turnIdx) {
  for (let i = turnIdx - 1; i >= 0; i -= 1) {
    if (store.turns[i]?.role === "operator") return store.turns[i].text;
  }
  return null;
}

function _resetCmdFailureState(store) {
  store._cmdFailedCorrIds = {};
}

function _clearStalePendingCmdAck(store, operatorText) {
  const ackIdx = _findCmdAckTurn(store, null);
  if (ackIdx < 0) return;
  const priorOp = _operatorTextBeforeTurn(store, ackIdx);
  if (priorOp === operatorText) return;
  _clearCmdStallTimer(store.turns[ackIdx]);
  store.turns.splice(ackIdx, 1);
}

const _IMAGINE_MODEL_LABELS = {
  zit: "Z-Image Turbo",
  "z-image": "Z-Image Turbo",
  krea2: "Krea 2 Turbo",
  "krea-2": "Krea 2 Turbo",
  "ideogram-local": "Ideogram 4 Local",
  comfyui: "Ideogram 4 Local",
};

function _imagineAckLabel(text) {
  const trimmed = String(text || "").trim();
  const modelMatch = trimmed.match(/\bmodel=([^\s]+)/i);
  const model = modelMatch?.[1]?.toLowerCase();
  return _IMAGINE_MODEL_LABELS[model] || "selected model";
}

const _LONG_RUNNING_CMD_ACK = {
  blend: "Running Blender…",
};

function _longRunningCmdAckText(text) {
  const trimmed = String(text || "").trim();
  if (!trimmed.startsWith("/")) return null;
  const name = trimmed.slice(1).split(/\s+/)[0]?.toLowerCase();
  if (name === "imagine" || name === "img") {
    return `Generating image… ${_imagineAckLabel(text)} may take up to a minute while models load.`;
  }
  return _LONG_RUNNING_CMD_ACK[name] || null;
}

function _showOptimisticCmdAck(store, text) {
  const ackText = _longRunningCmdAckText(text);
  if (!ackText) return false;
  _resetCmdFailureState(store);
  _clearStalePendingCmdAck(store, text);
  _upsertCmdMayaTurn(store, {
    corrId: null,
    text: ackText,
    cmdPhase: "ack",
    operatorText: text,
  });
  const turn = store.turns[store.turns.length - 1];
  if (turn?.cmdPhase === "ack") {
    turn._optimisticAck = true;
    turn._cmdOperatorText = text;
  }
  store._expectingReply = true;
  _persistConversation(store);
  _scrollTranscript();
  return true;
}

function _findCmdAckTurn(store, corrId) {
  if (corrId) {
    const exact = store.turns.findIndex((t) => t.corrId === corrId && t.cmdPhase === "ack");
    if (exact >= 0) return exact;
  }
  for (let i = store.turns.length - 1; i >= 0; i -= 1) {
    const t = store.turns[i];
    if (t.role === "maya" && t.cmdPhase === "ack" && t._cmdPending) return i;
  }
  const optimistic = store.turns.findIndex(
    (t) => t._optimisticAck && t.role === "maya" && t.cmdPhase === "ack" && t._cmdPending,
  );
  return optimistic;
}

function _clearCmdStallTimer(turn) {
  if (turn?._cmdStallTimer) {
    clearTimeout(turn._cmdStallTimer);
    turn._cmdStallTimer = null;
  }
}

function _scheduleCmdStallHint(store, corrId) {
  const stallMs = 180000;
  return setTimeout(() => {
    const idx = _findCmdAckTurn(store, corrId);
    if (idx < 0) return;
    const turn = store.turns[idx];
    if (!turn?._cmdPending) return;
    store.turns.push({
      messageId: _nextMessageId(),
      corrId,
      role: "system",
      text: "Still generating… check gateway logs if this persists.",
      sentAt: Date.now(),
    });
    _persistConversation(store);
    _scrollTranscript();
  }, stallMs);
}

function _findCmdDoneTurn(store, corrId, messageId) {
  if (messageId) {
    const byId = store.turns.findIndex(
      (t) => t.messageId === messageId && t.role === "maya" && (t.cmdPhase === "done" || t.cmdPhase === "remark"),
    );
    if (byId >= 0) return byId;
  }
  for (let i = store.turns.length - 1; i >= 0; i -= 1) {
    const t = store.turns[i];
    if (t.role === "maya" && t.corrId === corrId && (t.cmdPhase === "done" || t._remarkStreaming)) return i;
  }
  return -1;
}

function _upsertCmdMayaTurn(store, {
  corrId,
  text,
  artifacts,
  cmdPhase,
  messageId,
  operatorText,
  traceId,
  jobId,
  ev,
}) {
  if (cmdPhase === "remark") {
    const doneIdx = _findCmdDoneTurn(store, corrId, messageId);
    if (doneIdx >= 0) {
      const turn = store.turns[doneIdx];
      const chunk = String(text || "");
      if (!turn._remarkStreaming) {
        turn.text = "";
        turn._remarkStreaming = true;
      }
      if (chunk) turn.text = (turn.text || "") + chunk;
      turn.cmdPhase = "done";
      turn._cmdPending = false;
      if (messageId) turn.messageId = messageId;
      if (artifacts?.length) turn.artifacts = artifacts;
      _applyImagineTurnMeta(turn, { traceId, jobId, artifacts, ev });
      _persistConversation(store);
      _scrollTranscript();
      return true;
    }
  }
  const ackIdx = _findCmdAckTurn(store, corrId);
  if (ackIdx >= 0 && cmdPhase !== "ack") {
    const turn = store.turns[ackIdx];
    turn.text = text;
    turn.cmdPhase = cmdPhase || "done";
    turn._cmdPending = false;
    _clearCmdStallTimer(turn);
    if (messageId) turn.messageId = messageId;
    if (artifacts?.length) turn.artifacts = artifacts;
    _applyImagineTurnMeta(turn, { traceId, jobId, artifacts, ev });
    _applyPendingTurnMeta(store, turn);
    _finalizeChatMs(store);
    store._chatPendingAt = null;
    store._expectingReply = false;
    _persistConversation(store);
    _scrollTranscript();
    return true;
  }
  if (cmdPhase === "ack") {
    if (_isCmdFailed(store, corrId)) return true;
    if (ackIdx >= 0) {
      const turn = store.turns[ackIdx];
      const priorOp = _operatorTextBeforeTurn(store, ackIdx);
      if (operatorText && priorOp && priorOp !== operatorText) {
        _clearCmdStallTimer(turn);
        store.turns.splice(ackIdx, 1);
      } else {
        if (corrId && turn.corrId !== corrId) turn.corrId = corrId;
        if (corrId) turn._optimisticAck = false;
        if (operatorText) turn._cmdOperatorText = operatorText;
        if (text && turn.text !== text) turn.text = text;
        return true;
      }
    }
    if (_findMayaTurnByCorr(store, corrId) >= 0) return true;
    const turn = {
      messageId: messageId || _nextMessageId(),
      corrId,
      role: "maya",
      text,
      cmdPhase: "ack",
      _cmdPending: true,
      _streaming: false,
    };
    if (operatorText) turn._cmdOperatorText = operatorText;
    turn._cmdStallTimer = _scheduleCmdStallHint(store, corrId);
    store.turns.push(turn);
    store._chatPendingAt = store._chatPendingAt || Date.now();
    store._expectingReply = true;
    _persistConversation(store);
    _scrollTranscript();
    return true;
  }
  if (_hasCmdReply(store, corrId, text)) return true;
  store.turns.push({
    messageId: messageId || _nextMessageId(),
    corrId,
    role: "maya",
    text,
    cmdPhase: cmdPhase || "done",
    _streaming: false,
    artifacts: artifacts?.length ? artifacts : undefined,
  });
  _applyImagineTurnMeta(store.turns[store.turns.length - 1], { traceId, jobId, artifacts, ev });
  _applyPendingTurnMeta(store, store.turns[store.turns.length - 1]);
  _finalizeChatMs(store);
  store._chatPendingAt = null;
  store._expectingReply = false;
  _persistConversation(store);
  _scrollTranscript();
  return true;
}

function _formatCmdError(raw) {
  const detail = String(raw || "command failed").trim();
  let title = "Command failed";
  let hint = "";
  if (!detail || /^command failed$/i.test(detail)) {
    title = "Image generation failed";
    hint = "Check gateway logs for this corr_id. ComfyUI may still be loading models.";
  } else if (/failed with no details/i.test(detail)) {
    title = "Image generation failed";
    hint = "Check gateway logs for this corr_id. The job ended without a reason (gateway reload or ComfyUI issue).";
  } else if (/weights not visible|Z-Image weights missing|weights missing/i.test(detail)) {
    title = "Image generation failed";
    hint = "Z-Image model weights are not mounted in ComfyUI. See infra/comfyui/README.md.";
  } else if (/cancelled.*gateway may have reloaded/i.test(detail)) {
    title = "Image generation cancelled";
    hint = "The gateway may have reloaded during generation. Retry /imagine.";
  } else if (/requires ComfyUI 0\.26|CLIPLoader type `krea2`|not supported by this ComfyUI build/i.test(detail)) {
    title = "Image generation failed";
    hint = detail;
  } else if (/COMFYUI_API_URL|comfyui-api|ComfyUI is not reachable/i.test(detail)) {
    title = "Image generation failed";
    hint = "ComfyUI is unavailable. Start comfyui-api or check Settings → Imagine → ComfyUI URL.";
  } else if (/disabled in Settings/i.test(detail)) {
    title = "Image generation disabled";
    hint = "Enable Imagine in Settings → Imagine.";
  } else if (/OOM|VRAM|GPU memory|out of memory/i.test(detail)) {
    title = "Image generation failed";
    hint = "GPU memory may be full. Stop other GPU workloads or try a smaller model.";
  } else if (/event loop|timed out after \d+s/i.test(detail) || /timed out|timeout/i.test(detail)) {
    title = "Image generation timed out";
    hint = "ComfyUI took too long. Try again or check GPU load.";
  }
  const text = hint ? `${title}\n${hint}` : detail;
  return { text, detail, cmdError: hint.length > 0 || title !== "Command failed" };
}

const _SERVER_CLEAR_WINDOW_MS = 30000;

function _markSseHandledCorr(store, corrId) {
  if (!corrId) return;
  if (!store._sseHandledCorrIds) store._sseHandledCorrIds = {};
  store._sseHandledCorrIds[corrId] = true;
}

function _sseAlreadyHandledForHttp(store, corrId, operatorText) {
  if (corrId && store._sseHandledCorrIds?.[corrId]) return true;
  if (corrId && _findMayaTurnByCorr(store, corrId) >= 0) return true;
  const opIdx = _findOperatorTurnByText(store, operatorText);
  if (opIdx < 0) return false;
  for (let i = opIdx + 1; i < store.turns.length; i += 1) {
    const t = store.turns[i];
    if (t?.role === "maya" && (t.text || t.artifacts?.length)) return true;
    if (t?.role === "operator") break;
  }
  return false;
}

function _ensureOperatorTurn(store, text, corrId, messageId) {
  const opIdx = _findOperatorTurnByText(store, text);
  if (opIdx >= 0) {
    const op = store.turns[opIdx];
    if (corrId && !op.corrId) op.corrId = corrId;
    if (messageId && _isServerId(messageId)) op.messageId = messageId;
    return;
  }
  store.turns.push({
    messageId: messageId && _isServerId(messageId) ? messageId : _nextMessageId(),
    corrId: corrId || null,
    role: "operator",
    text,
    sentAt: Date.now(),
  });
  _persistConversation(store);
  _scrollTranscript();
}

function _applyChatHttpResponse(store, data, operatorText) {
  if (!data || !data.ok || data.mode === "cmd") return;
  const corrId = data.corr_id || null;
  if (_sseAlreadyHandledForHttp(store, corrId, operatorText)) {
    if (corrId) {
      const opIdx = _findOperatorTurnByText(store, operatorText);
      if (opIdx >= 0 && !store.turns[opIdx].corrId) store.turns[opIdx].corrId = corrId;
    }
    store._chatPendingAt = null;
    store._expectingReply = false;
    _persistConversation(store);
    return;
  }
  const replyText = String(data.text || "").trim();
  _ensureOperatorTurn(store, operatorText, corrId);
  if (!replyText) {
    store._chatPendingAt = null;
    store._expectingReply = false;
    _persistConversation(store);
    return;
  }
  if (_findMayaTurnByCorr(store, corrId) >= 0) return;
  const last = store.turns[store.turns.length - 1];
  if (last?.role === "maya" && last.text?.trim() === replyText) return;
  store.turns.push({
    messageId: _nextMessageId(),
    corrId,
    role: "maya",
    text: data.text || "",
    _streaming: false,
  });
  _finalizeChatMs(store);
  store._chatPendingAt = null;
  store._expectingReply = false;
  _persistConversation(store);
  _scrollTranscript();
}

function _applyCmdResponse(store, data, operatorText) {
  if (!data || data.mode !== "cmd") return;
  const corrId = data.corr_id || null;
  if (data.pending && data.cmd_phase === "ack") {
    const lastOp = store.turns[store.turns.length - 1];
    if (lastOp?.role === "operator" && lastOp.text === operatorText && corrId) {
      lastOp.corrId = corrId;
    }
    for (let i = store.turns.length - 1; i >= 0; i -= 1) {
      const t = store.turns[i];
      if (t.role === "maya" && t.cmdPhase === "ack" && t._cmdPending && corrId && t.corrId !== corrId) {
        t.corrId = corrId;
        break;
      }
    }
    _upsertCmdMayaTurn(store, {
      corrId,
      text: data.text || "Working on it…",
      cmdPhase: "ack",
    });
    return;
  }
  if (data.ok) {
    const opIdx = _findOperatorTurnByText(store, operatorText);
    if (opIdx < 0) {
      store.turns.push({
        messageId: _nextMessageId(),
        corrId,
        role: "operator",
        text: operatorText,
        sentAt: Date.now(),
      });
    } else if (corrId && !store.turns[opIdx].corrId) {
      store.turns[opIdx].corrId = corrId;
    }
    _upsertCmdMayaTurn(store, {
      corrId,
      text: data.text || "",
      artifacts: data.artifacts,
      cmdPhase: "done",
      traceId: data.trace_id || null,
      jobId: data.job_id || null,
    });
    return;
  }
  const formatted = _formatCmdError(data.error || data.text || "command failed");
  const ackIdx = _findCmdAckTurn(store, corrId);
  if (ackIdx >= 0) {
    _clearCmdStallTimer(store.turns[ackIdx]);
    store.turns.splice(ackIdx, 1);
  }
  _markCmdFailed(store, corrId);
  store.turns.push({
    messageId: _nextMessageId(),
    corrId,
    traceId: data.trace_id || null,
    jobId: data.job_id || null,
    role: "system",
    text: formatted.text,
    detail: formatted.detail,
    cmdError: formatted.cmdError,
    sentAt: Date.now(),
  });
  store._chatPendingAt = null;
  store._expectingReply = false;
  _persistConversation(store);
  _scrollTranscript();
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
    } else if (v === "idle") {
      for (const t of store.turns) {
        if (t._remarkStreaming) t._remarkStreaming = false;
      }
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
  if (ev.type === "error" && ev.text) {
    if (ev.mode === "cmd") {
      const formatted = _formatCmdError(ev.text);
      const corrId = _evCorrId(ev);
      let ackIdx = _findCmdAckTurn(store, corrId);
      if (ackIdx < 0) {
        ackIdx = store.turns.findIndex(
          (t) => t._optimisticAck && t.cmdPhase === "ack" && t._cmdPending,
        );
      }
      if (ackIdx >= 0) {
        _clearCmdStallTimer(store.turns[ackIdx]);
        store.turns.splice(ackIdx, 1);
      }
      _markCmdFailed(store, corrId);
      store.turns.push({
        messageId: ev.message_id || _nextMessageId(),
        corrId,
        traceId: ev.trace_id || null,
        jobId: ev.job_id || null,
        role: "system",
        text: formatted.text,
        detail: formatted.detail,
        cmdError: formatted.cmdError,
        sentAt: Date.now(),
      });
      store._chatPendingAt = null;
      store._expectingReply = false;
      _persistConversation(store);
      _scrollTranscript();
      return;
    }
    if (store.ttsBusy) {
      store.ttsError = ev.text;
      store.ttsBusy = false;
      store._ttsPreviewOnly = false;
      return;
    }
    if (store._chatPendingAt || ev.mode === "cmd") {
      store.turns.push({
        messageId: _nextMessageId(),
        corrId: _evCorrId(ev),
        role: "system",
        text: ev.text,
      });
      store._chatPendingAt = null;
      store._expectingReply = false;
      _persistConversation(store);
      _scrollTranscript();
      return;
    }
  }
  if (ev.type === "tts_error" && ev.text) {
    store.ttsError = ev.text;
    store.ttsBusy = false;
    store._ttsPreviewOnly = false;
    return;
  }
  if (ev.type === "user" && ev.text) {
    const corrId = _evCorrId(ev);
    const opIdx = _findOperatorTurnByText(store, ev.text);
    if (opIdx >= 0) {
      const op = store.turns[opIdx];
      if (corrId && !op.corrId) op.corrId = corrId;
      if (ev.message_id && _isServerId(ev.message_id)) op.messageId = ev.message_id;
      store._chatPendingAt = Date.now();
      store._ttsPendingAt = null;
      store._ttsPendingIdx = null;
      store._ttsTargetIdx = null;
      _persistConversation(store);
      _scrollTranscript();
      return;
    }
    store.turns.push({
      messageId: ev.message_id || _nextMessageId(),
      corrId,
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
  if (ev.type === "ai" && (ev.text || ev.artifacts?.length)) {
    const corrId = _evCorrId(ev);
    if (corrId && (ev.artifacts?.length || ev.text)) {
      _markSseHandledCorr(store, corrId);
    }
    const chunk = String(ev.text || "");
    const isFinal = ev.final === true;
    const isCmd = ev.mode === "cmd";
    const last = store.turns[store.turns.length - 1];
    if (last && last.role === "maya" && !last._streaming && chunk.trim() === (last.text || "").trim()) {
      if (ev.artifacts?.length && !last.artifacts?.length) {
        last.artifacts = ev.artifacts;
        _applyImagineTurnMeta(last, {
          traceId: ev.trace_id || null,
          jobId: ev.job_id || null,
          artifacts: ev.artifacts,
          ev,
        });
        _persistConversation(store);
        _scrollTranscript();
      }
      return;
    }
    let turn = _findMayaTurnForEvent(store, ev);
    const streamingMaya = turn && turn._streaming;
    const allowReply =
      streamingMaya ||
      turn ||
      store._expectingReply ||
      store._chatPendingAt != null ||
      isCmd ||
      isFinal ||
      (ev.artifacts?.length > 0);
    if (!allowReply) return;

    if (isCmd) {
      _upsertCmdMayaTurn(store, {
        corrId,
        text: chunk,
        artifacts: ev.artifacts,
        cmdPhase: ev.cmd_phase || "done",
        messageId: ev.message_id,
        traceId: ev.trace_id || null,
        jobId: ev.job_id || null,
        ev,
      });
      return;
    }

    if (turn) {
      if (ev.message_id) turn.messageId = ev.message_id;
      if (corrId) turn.corrId = corrId;
      if (ev.artifacts?.length) {
        turn.artifacts = ev.artifacts;
        _applyImagineTurnMeta(turn, {
          traceId: ev.trace_id || null,
          jobId: ev.job_id || null,
          artifacts: ev.artifacts,
          ev,
        });
      }
      if (chunk && turn.artifacts?.length) turn._remarkStreaming = true;
      if (chunk) {
        if (!_mergeAiChunk(turn, chunk, { final: isFinal })) {
          if (ev.artifacts?.length) {
            _persistConversation(store);
            _scrollTranscript();
          }
          return;
        }
      } else if (!ev.artifacts?.length) {
        return;
      }
      if (isFinal) turn._streaming = false;
      else if (!turn._streaming) turn._streaming = true;
      _applyPendingTurnMeta(store, turn);
    } else {
      const mayaTurn = {
        messageId: ev.message_id || _nextMessageId(),
        corrId,
        role: "maya",
        text: chunk,
        _streaming: chunk ? !isFinal : false,
      };
      if (ev.artifacts?.length) {
        mayaTurn.artifacts = ev.artifacts;
      }
      store.turns.push(mayaTurn);
      const added = store.turns[store.turns.length - 1];
      if (chunk && added.artifacts?.length) added._remarkStreaming = true;
      _applyPendingTurnMeta(store, added);
      if (ev.artifacts?.length) {
        _applyImagineTurnMeta(added, {
          traceId: ev.trace_id || null,
          jobId: ev.job_id || null,
          artifacts: ev.artifacts,
          ev,
        });
      }
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
    visionActive: false,
    visionLabel: "",
    visionError: "",
    sending: false,
    detailed: true,
    sidebarOpen: true,
    _expectingReply: false,
    _activeTurnAudio: null,
    _activeTurnMessageId: null,
    _hydrated: false,
    _basicChatNoted: false,
    _chatPendingAt: null,
    _clearedAt: null,
    _ttsPendingAt: null,
    _ttsPendingIdx: null,
    _ttsTargetIdx: null,
    _ttsPreviewOnly: false,
    _pendingTtsModel: null,
    _pendingDeliveryCue: null,
    _cmdFailedCorrIds: {},
    _sseHandledCorrIds: {},
    _visionUnsub: null,

    _syncVisionState() {
      const cap = window.mayaVisionCapture;
      if (!cap) return;
      this.visionActive = !!cap.active;
      this.visionLabel = cap.label || "";
      this.visionError = cap.error || "";
    },

    async startVisionShare() {
      const cap = window.mayaVisionCapture;
      if (!cap) return;
      const result = await cap.startShare();
      this._syncVisionState();
      if (!result.ok && result.error) {
        this.turns.push({ messageId: _nextMessageId(), role: "system", text: result.error });
        this.persist();
        _scrollTranscript();
      }
    },

    async stopVisionShare() {
      const cap = window.mayaVisionCapture;
      if (!cap) return;
      await cap.stopShare();
      this._syncVisionState();
    },

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
        const stored = sessionStorage.getItem(_detailedStorageKey());
        this.detailed = stored === null ? true : stored === "1";
      } catch (_) {}
      try {
        const stored = sessionStorage.getItem(_sidebarStorageKey());
        if (stored !== null) this.sidebarOpen = stored === "1";
      } catch (_) {}
    },

    formatSentAt(ts) {
      return _formatSentAt(ts);
    },

    imagineBodyHidden(turn) {
      return _imagineTurnBodyHidden(turn);
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
      if (turn.imagineModel) parts.push({ text: turn.imagineModel });
      if (turn.genMs != null) parts.push({ text: `gen ${_formatDuration(turn.genMs)}` });
      if (turn.corrId) parts.push({ text: turn.corrId, dim: !_isServerId(turn.corrId) });
      if (turn.chatMs != null) {
        const tripLabel = turn.imagineModel || turn.genMs != null ? "trip" : "chat";
        parts.push({ text: `${tripLabel} ${_formatDuration(turn.chatMs)}` });
      }
      const tts = turn.ttsMs != null ? _formatDuration(turn.ttsMs) : "—";
      let ttsPart = `TTS ${tts}`;
      if (turn.ttsTtfaMs != null) ttsPart += ` (ttfa ${_formatDuration(turn.ttsTtfaMs)})`;
      if ((turn.ttsCached || turn.ttsReplay) && turn.ttsMs != null) ttsPart += " (cached)";
      if (turn.ttsModel) parts.push({ text: ttsPart + ` · ${turn.ttsModel}` });
      else parts.push({ text: ttsPart });
      if (turn.workflowName) parts.push({ text: turn.workflowName, dim: true });
      if (turn.traceId) parts.push({ text: `trace ${turn.traceId}`, dim: true });
      if (turn.jobId) parts.push({ text: `job ${turn.jobId}`, dim: true });
      const remarkHint = _imagineRemarkHint(turn);
      if (remarkHint) parts.push(remarkHint);
      if (turn.messageId) parts.push({ text: turn.messageId, dim: !_isServerId(turn.messageId) });
      if (turn.completionId) parts.push({ text: `cmpl ${turn.completionId}` });
      return parts;
    },

    systemMetaParts(turn) {
      const parts = [];
      if (turn.sentAt) parts.push({ text: `sent ${_formatSentAt(turn.sentAt)}` });
      if (turn.corrId) parts.push({ text: turn.corrId, dim: !_isServerId(turn.corrId) });
      if (turn.traceId) parts.push({ text: `trace ${turn.traceId}` });
      if (turn.jobId) parts.push({ text: `job ${turn.jobId}` });
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
          if (Array.isArray(d.turns)) {
            if (d.turns.length === 0) {
              const clearedAt = this._clearedAt;
              const clearedRecently =
                clearedAt != null && Date.now() - clearedAt < _SERVER_CLEAR_WINDOW_MS;
              const pendingChat = this._chatPendingAt != null;
              const hasTurnsAfterClear = this.turns.some(
                (t) => t.sentAt && clearedAt != null && t.sentAt > clearedAt,
              );
              if (clearedRecently && !pendingChat && !hasTurnsAfterClear) {
                this.turns = [];
              }
            } else if (d.turns.length > this.turns.length) {
              this.turns = _mergeServerTurns(this.turns, d.turns);
            }
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
      this._syncVisionState();
      if (!this._visionUnsub && window.mayaVisionCapture?.subscribe) {
        this._visionUnsub = window.mayaVisionCapture.subscribe(() => this._syncVisionState());
      }
      window.addEventListener("maya-session-stop", () => {
        this.stopVisionShare();
      });
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
      let fetchHangTimer = null;
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
        _ensureOperatorTurn(this, text, null);
        if (!caps.text_chat_enriched && !this._basicChatNoted) {
          this._basicChatNoted = true;
          this.turns.push({
            messageId: _nextMessageId(),
            role: "system",
            text: "Basic LLM replies — full agent (personality, memory, voice) still loading.",
          });
        }
        _showOptimisticCmdAck(this, text);
        const isLongCmd = !!_longRunningCmdAckText(text);
        if (isLongCmd) {
          fetchHangTimer = setTimeout(() => {
            if (!this._chatPendingAt) return;
            const ackIdx = _findCmdAckTurn(this, null);
            const opForAck = ackIdx >= 0 ? _operatorTextBeforeTurn(this, ackIdx) : null;
            if (opForAck !== text) return;
            this.turns.push({
              messageId: _nextMessageId(),
              role: "system",
              text: "Still waiting for gateway… it may be reloading. Retry after restart if this persists.",
              sentAt: Date.now(),
            });
            this.persist();
            _scrollTranscript();
          }, 30000);
        }
        const r = await fetch("/api/voice/agent/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
        if (fetchHangTimer) clearTimeout(fetchHangTimer);
        if (!r.ok) {
          let errMsg = `Chat failed (${r.status})`;
          try {
            const errBody = await r.json();
            errMsg = errBody.error || errBody.detail || errMsg;
          } catch (_) {}
          this.turns.push({ messageId: _nextMessageId(), role: "system", text: String(errMsg) });
          this.persist();
          _scrollTranscript();
          return;
        }
        const data = await r.json();
        if (data.mode === "cmd") {
          _applyCmdResponse(this, data, text);
        } else if (!data.ok) {
          this.turns.push({ messageId: _nextMessageId(), role: "system", text: data.error || "Chat failed" });
          this.persist();
          _scrollTranscript();
        } else if (this.enrichedChatReady || _sseAlreadyHandledForHttp(this, data.corr_id, text)) {
          const corrId = data.corr_id || null;
          if (corrId) {
            const opIdx = _findOperatorTurnByText(this, text);
            if (opIdx >= 0 && !this.turns[opIdx].corrId) {
              this.turns[opIdx].corrId = corrId;
            }
          }
          this._chatPendingAt = null;
          this._expectingReply = false;
          this.persist();
        } else {
          _applyChatHttpResponse(this, data, text);
        }
      } catch (err) {
        const ackIdx = _findCmdAckTurn(this, null);
        const opForAck = ackIdx >= 0 ? _operatorTextBeforeTurn(this, ackIdx) : null;
        if (ackIdx >= 0 && opForAck === text) {
          _clearCmdStallTimer(this.turns[ackIdx]);
          this.turns.splice(ackIdx, 1);
        }
        this.turns.push({
          messageId: _nextMessageId(),
          role: "system",
          text: String(err?.message || err) || "Chat request failed — gateway may have reloaded.",
        });
        this.persist();
        _scrollTranscript();
      } finally {
        if (fetchHangTimer) clearTimeout(fetchHangTimer);
        this.sending = false;
        if (!this.turns.some((t) => t.cmdPhase === "ack" && t._cmdPending)) {
          this.step = "listen";
        }
      }
    },

    onKeydown(e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this.sendServer();
      }
    },

    resetLocal() {
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
      this._sseHandledCorrIds = {};
      this.persist();
      _scrollTranscript(false);
    },

    async newChat() {
      try {
        const r = await fetch("/api/voice/agent/conversation/clear", { method: "POST" });
        if (r.ok) {
          const data = await r.json();
          if (data.ok) this._clearedAt = Date.now();
        }
      } catch (_) {}
      this.resetLocal();
    },

    reset() {
      return this.newChat();
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
    get visionReady() {
      const shell = Alpine.store("mayaShell");
      const store = Alpine.store("mayaConversation");
      return shell?.capabilities?.vision === true && !store?.useWebLLM;
    },
    get useWebLLM() {
      return Alpine.store("mayaConversation")?.useWebLLM || false;
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
