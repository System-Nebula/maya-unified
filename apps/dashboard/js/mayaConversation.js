/** Conversation state — shared across dashboard pages + sessionStorage (per operator). */
function _storageKey() {
  const uid = window._mayaCurrentUser?.id || "anonymous";
  return `maya.conversation.v1.${uid}`;
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
  if (ev.type === "status") {
    const v = ev.value || "idle";
    store.statusLabel = v;
    if (v === "listening" || v === "hearing") {
      store.step = "listen";
      if (store.ttsBusy) store.ttsBusy = false;
    } else if (v === "transcribing") store.step = "detect";
    else if (v === "thinking") store.step = "reason";
    else if (v === "speaking") store.step = "maya";
    else if (v === "idle") {
      const last = store.turns[store.turns.length - 1];
      if (last && last._streaming) last._streaming = false;
      if (store.ttsBusy) store.ttsBusy = false;
    }
    _persistConversation(store);
    return;
  }
  if (ev.type === "error" && ev.text && store.ttsBusy) {
    store.ttsError = ev.text;
    store.ttsBusy = false;
    return;
  }
  if (ev.type === "tts_error" && ev.text) {
    store.ttsError = ev.text;
    store.ttsBusy = false;
    return;
  }
  if (ev.type === "user" && ev.text) {
    const last = store.turns[store.turns.length - 1];
    if (last && last.role === "operator" && last.text === ev.text) return;
    store.turns.push({ role: "operator", text: ev.text });
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
        _persistConversation(store);
        _scrollTranscript();
        return;
      }
      last.text = cur + chunk;
    } else {
      store.turns.push({ role: "maya", text: chunk, _streaming: true });
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
    _hydrated: false,

    persist() {
      _persistConversation(this);
    },

    restore() {
      _restoreConversation(this);
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

    async speakPreview() {
      const text = this.ttsDraft.trim();
      if (!text || this.ttsBusy || !Alpine.store("mayaShell")?.ready) return;
      this.ttsBusy = true;
      this.ttsError = "";
      this.step = "maya";
      try {
        const body = { text };
        const instruct = this.ttsInstruct.trim();
        if (instruct) body.instruct = instruct;
        const r = await fetch("/api/voice/agent/speak", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        let data = {};
        try {
          data = await r.json();
        } catch (_) {
          data = {};
        }
        if (!r.ok) {
          const detail = data.detail || data.error;
          this.ttsError =
            detail ||
            (r.status === 404
              ? "Speak API not found — restart launch.py to load the new route."
              : `Speak failed (HTTP ${r.status})`);
          this.ttsBusy = false;
          this.step = "listen";
          return;
        }
        if (!data.ok) {
          this.ttsError = data.error || "Speak failed";
          this.ttsBusy = false;
          this.step = "listen";
        }
      } catch (e) {
        this.ttsError = String(e.message || e);
        this.ttsBusy = false;
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
      const agentReady = shell?.ready || false;
      const llmOk = shell?.llmOk !== false && shell?.ready;
      this.sending = true;
      this.draft = "";
      this.step = "reason";
      try {
        if (agentReady && llmOk) {
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
        } else {
          this.turns.push({ role: "operator", text });
          this.turns.push({
            role: "system",
            text: "Demo mode — agent still loading. Using rule-based /api/voice/turn (not your LLM).",
          });
          const r = await fetch("/api/voice/turn", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ transcript: text }),
          });
          if (r.ok) {
            const data = await r.json();
            this.turns.push({ role: "maya", text: data.maya_turn });
          }
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
      return Alpine.store("mayaShell")?.llmOk !== false && Alpine.store("mayaShell")?.ready;
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
