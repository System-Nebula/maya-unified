/** Conversation state — shared across dashboard pages + sessionStorage (per operator). */
function _storageKey() {
  const uid = window._mayaCurrentUser?.id || "anonymous";
  return `maya.conversation.v1.${uid}`;
}

function _detailedStorageKey() {
  const uid = window._mayaCurrentUser?.id || "anonymous";
  return `maya.conversation.detailed.v1.${uid}`;
}

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

function _lastMayaTurnIdx(store) {
  for (let i = store.turns.length - 1; i >= 0; i--) {
    if (store.turns[i]?.role === "maya") return i;
  }
  return -1;
}

function _endStreaming(store) {
  const last = store.turns[store.turns.length - 1];
  if (last?._streaming) last._streaming = false;
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
  store.playingTurnIdx = idx;
  if (turn.ttsMs != null || store._ttsPendingAt != null) return;
  store._ttsPendingAt = Date.now();
  store._ttsPendingIdx = idx;
}

function _clearPlayingTurn(store) {
  store.playingTurnIdx = null;
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

function _persistConversation(store) {
  try {
    sessionStorage.setItem(
      _storageKey(),
      JSON.stringify({
        turns: store.turns,
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
    if (Array.isArray(data.turns)) store.turns = data.turns;
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
      if (!store._ttsPreviewOnly) _clearPlayingTurn(store);
      if (store.ttsBusy) {
        store.ttsBusy = false;
        store._ttsPreviewOnly = false;
      }
    } else if (v === "transcribing") store.step = "detect";
    else if (v === "thinking") store.step = "reason";
    else if (v === "speaking") {
      store.step = "maya";
      _endStreaming(store);
      _finalizeChatMs(store);
      _onTtsStart(store);
    } else if (v === "idle") {
      _endStreaming(store);
      _finalizeChatMs(store);
      if (!store._ttsPreviewOnly) _clearPlayingTurn(store);
      if (store.ttsBusy) {
        store.ttsBusy = false;
        store._ttsPreviewOnly = false;
      }
    }
    _persistConversation(store);
    return;
  }
  if (ev.type === "audio_stop") {
    if (!store._ttsPreviewOnly) _clearPlayingTurn(store);
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
    store.turns.push({ role: "operator", text: ev.text, sentAt: Date.now() });
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
    if (last && last.role === "maya" && last._streaming) {
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
      const turn = { role: "maya", text: chunk, _streaming: true };
      _applyPendingTurnMeta(store, turn);
      store.turns.push(turn);
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
    playingTurnIdx: null,
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

    restore() {
      _restoreConversation(this);
      try {
        this.detailed = sessionStorage.getItem(_detailedStorageKey()) === "1";
      } catch (_) {}
    },

    formatSentAt(ts) {
      return _formatSentAt(ts);
    },

    formatMayaMeta(turn) {
      const parts = [];
      if (turn.deliveryCue) {
        parts.push(`Maya · ${turn.deliveryCue}`);
      }
      if (turn.chatMs != null) parts.push(`chat ${_formatDuration(turn.chatMs)}`);
      const tts = turn.ttsMs != null ? _formatDuration(turn.ttsMs) : "—";
      let ttsPart = `TTS ${tts}`;
      if (turn.ttsReplay && turn.ttsMs != null) ttsPart += " (cached)";
      if (turn.ttsModel) ttsPart += ` · ${turn.ttsModel}`;
      parts.push(ttsPart);
      return parts.join(" · ");
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
            this.turns = d.turns;
            _scrollTranscript();
          }
        }
        this.persist();
      } catch (_) {}
    },

    async ensureHydrated() {
      if (this._hydrated) return;
      this.restore();
      await this.loadSettings();
      await this.syncFromServer();
      this._hydrated = true;
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
        this.turns.push({ role: "system", text: `Voice is in use by ${who}. Try again when they finish.` });
        this.persist();
        _scrollTranscript();
      } else {
        this.turns.push({ role: "system", text: data.error || "Could not start session" });
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

    async toggleTurnPlay(idx) {
      if (this.playingTurnIdx === idx) {
        this.pauseTurn();
        return;
      }
      if (this.playingTurnIdx != null) this.pauseTurn();
      await this.playTurn(idx);
    },

    pauseTurn() {
      window.mayaBrowserAudioOutput?.stop?.();
      this.playingTurnIdx = null;
      this._ttsTargetIdx = null;
      this._ttsPendingAt = null;
      this._ttsPendingIdx = null;
    },

    async playTurn(idx) {
      const turn = this.turns[idx];
      if (!turn || turn.role !== "maya" || !turn.text?.trim()) return;
      if (turn.ttsMs != null) turn.ttsReplay = true;
      this._ttsTargetIdx = idx;
      this._ttsPendingAt = null;
      this._ttsPendingIdx = null;
      window.mayaBrowserAudioOutput?.resumeOutput?.();
      window.mayaBrowserAudioOutput?.resume?.();
      try {
        const r = await fetch("/api/voice/agent/speak", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: turn.text.trim() }),
        });
        let data = {};
        try {
          data = await r.json();
        } catch (_) {
          data = {};
        }
        if (!r.ok || !data.ok) {
          this.turns.push({
            role: "system",
            text: data.detail || data.error || `Speak failed (HTTP ${r.status})`,
          });
          this.persist();
          _scrollTranscript();
          this._ttsTargetIdx = null;
        }
      } catch (e) {
        this.turns.push({ role: "system", text: String(e.message || e) });
        this.persist();
        _scrollTranscript();
        this._ttsTargetIdx = null;
      }
    },

    async speakPreview() {
      const text = this.ttsDraft.trim();
      if (!text || this.ttsBusy || !Alpine.store("mayaShell")?.ready) return;
      window.mayaBrowserAudioOutput?.resume?.();
      this.ttsBusy = true;
      this.ttsError = "";
      this._ttsPreviewOnly = true;
      this.step = "maya";
      try {
        const body = { text };
        const instruct = this.ttsInstruct.trim();
        if (instruct) body.instruct = instruct;
        const r = await fetch("/api/voice/agent/tts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!r.ok) {
          let data = {};
          try {
            data = await r.json();
          } catch (_) {
            data = {};
          }
          this.ttsError =
            data.error ||
            data.detail ||
            (r.status === 404
              ? "TTS API not found — restart launch.py to load the new route."
              : `Speak failed (HTTP ${r.status})`);
          this.ttsBusy = false;
          this._ttsPreviewOnly = false;
          this.step = "listen";
          return;
        }
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
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
      try {
        if (!textChat) {
          this.turns.push({ role: "operator", text });
          const detail =
            shell?.llmHealth?.detail ||
            shell?.llmError ||
            "LLM unavailable — check Settings → Reasoning.";
          this.turns.push({ role: "system", text: detail });
          this.persist();
          _scrollTranscript();
          return;
        }
        if (!caps.text_chat_enriched && !this._basicChatNoted) {
          this._basicChatNoted = true;
          this.turns.push({
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
          this.turns.push({ role: "system", text: data.error || "Chat failed" });
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
      this.turns = [];
      this._chatPendingAt = null;
      this._ttsPendingAt = null;
      this._ttsPendingIdx = null;
      this._ttsTargetIdx = null;
      this.playingTurnIdx = null;
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
