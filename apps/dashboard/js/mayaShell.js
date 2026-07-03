/** Shared shell — nav, agent + LLM status, single SSE connection. */
(function () {
  const handlers = new Set();
  let es = null;

  function dispatch(ev) {
    handlers.forEach((fn) => {
      try { fn(ev); } catch (_) {}
    });
  }

  window.mayaAgentEvents = {
    subscribe(fn) {
      handlers.add(fn);
      if (!es) {
        es = new EventSource("/api/voice/agent/events");
        es.onmessage = (e) => dispatch(JSON.parse(e.data));
        es.onerror = () => { /* browser reconnects; ignore */ };
      }
      return () => handlers.delete(fn);
    },
  };
})();

document.addEventListener("alpine:init", () => {
  Alpine.store("mayaShell", {
    ready: false,
    status: "loading",
    error: "",
    llmOk: false,
    llmReady: false,
    llmError: "",
    llmModel: "",
    llmProvider: "",
    llmHealth: null,
    capabilities: {
      text_chat: false,
      text_chat_enriched: false,
      voice_session: false,
      tts_preview: false,
      eq_live: false,
      tools: false,
    },
    webllmBridgeStatus: "",
    voiceAvailable: true,
    voiceOwnerName: "",
    page: "",
    loadStarted: 0,

    shortWebLLMModel() {
      const id = this.llmModel || "";
      if (!id) return "model";
      return id.replace(/-q4f16_1-MLC$/i, "").replace(/-Instruct.*$/i, "");
    },

    label() {
      if (this.error) return "agent error";
      if (this.llmProvider === "webllm") {
        if (!this.llmReady && !this.ready) return "loading";
        if (!this.llmOk) return "experimental mode";
        return this.ready ? "experimental agent ready" : "chat ready";
      }
      if (this.llmReady && !this.ready) return "chat ready";
      if (!this.llmReady && !this.ready) {
        if (this.status === "loading") return "loading models";
        return this.status || "connecting";
      }
      if (this.ready && !this.llmOk) return "llm offline";
      if (this.ready && this.llmOk) return "agent ready";
      return this.status || "connecting";
    },

    chipClass() {
      if (this.error) return "error";
      if (this.llmProvider === "webllm" && this.ready && this.llmOk) return "ready experimental";
      if (this.llmReady && !this.ready) return "ready";
      if (this.ready && !this.llmOk) return "loading";
      if (this.ready) return "ready";
      return "loading";
    },

    hint() {
      if (this.error) return this.error.slice(0, 140);
      if (this.llmProvider === "webllm") {
        const model = this.shortWebLLMModel();
        if (!this.llmReady && !this.ready) {
          return (this.webllmBridgeStatus || this.llmError || "loading in browser…").slice(0, 140);
        }
        if (this.ready && !this.llmOk) {
          const st = this.webllmBridgeStatus || this.llmError || "loading in browser…";
          return `webllm: ${model} — ${st}`.slice(0, 140);
        }
        if (this.llmReady && !this.ready) return `webllm: ${model} — voice loading`;
        if (this.ready && this.llmOk) return `webllm: ${model}`;
      }
      if (this.llmReady && !this.ready) {
        return "Voice loading — text chat available".slice(0, 140);
      }
      if (!this.llmReady && !this.ready) {
        const detail = this.llmHealth?.detail || this.llmError;
        if (detail) return String(detail).slice(0, 140);
      }
      if (this.ready && !this.llmOk) {
        return (this.llmError || "Configure LLM in Settings → Reasoning.").slice(0, 140);
      }
      if (!this.ready && this.loadStarted) {
        const s = Math.floor((Date.now() - this.loadStarted) / 1000);
        if (s > 30) return "First load downloads TTS weights — can take several minutes.";
        if (s > 10) return "Loading STT + TTS on GPU…";
      }
      if (this.llmReady && this.llmModel) return this.llmModel;
      if (this.ready && this.llmOk && this.llmModel) return this.llmModel;
      return "";
    },
  });

  Alpine.data("mayaShell", () => ({
    get s() { return Alpine.store("mayaShell"); },
    currentUser: null,
    _unsub: null,
    _bound: false,

    init() {
      if (this._bound) return;
      this._bound = true;
      const path = window.location.pathname.replace(/\/$/, "") || "/";
      if (path === "/" || path === "/conversation") this.s.page = "dashboard";
      else if (path.startsWith("/settings")) this.s.page = "settings";
      else if (path.startsWith("/memory")) this.s.page = "memory";
      else if (path.startsWith("/admin")) this.s.page = "admin";
      else if (path.startsWith("/rooms")) this.s.page = "rooms";
      else if (path.startsWith("/experimental")) this.s.page = "experimental";
      this.s.loadStarted = Date.now();
      if (window.mayaConversationStore && this.s.page !== "settings") {
        window.mayaConversationStore.ensureHydrated();
      }
      this.pollStatus();
      this._unsub = window.mayaAgentEvents.subscribe((ev) => this.onAgentEvent(ev));
      if (this.s.page !== "settings") {
        this.syncSettingsToSdk();
        this.initWebLLMBridge();
      }
      setInterval(() => this.pollStatus(), 12000);
      this._bridgeTick = setInterval(() => this.refreshBridgeStatus(), 800);
      this.fetchCurrentUser();
    },

    async fetchCurrentUser() {
      try {
        const res = await fetch("/api/auth/me");
        if (!res.ok) return;
        const data = await res.json();
        if (data.authenticated) {
          this.currentUser = data;
          window._mayaCurrentUser = data;
          if (window.mayaConversationStore) window.mayaConversationStore.ensureHydrated();
        }
      } catch (_) {}
    },

    async signOut() {
      try {
        await fetch("/api/auth/logout", { method: "POST" });
      } catch (_) {}
      window.location.href = "/login";
    },

    refreshBridgeStatus() {
      const bridge = window.mayaWebLLMBridge;
      this.s.webllmBridgeStatus = bridge?.status || "";
      if (this.s.llmProvider === "webllm" && bridge?.ready && !this.s.llmOk) {
        this.pollStatus();
      }
    },

    async initWebLLMBridge() {
      try {
        const r = await fetch("/api/voice/settings");
        if (!r.ok) return;
        const data = await r.json();
        const reas = data.settings?.reasoning || {};
        const isWebllm = reas.provider === "webllm";
        const modelId = reas.webllm?.model_id || "Llama-3.1-8B-Instruct-q4f16_1-MLC";
        if (window.mayaWebLLMBridge) {
          await window.mayaWebLLMBridge.init(isWebllm, modelId);
          this.refreshBridgeStatus();
          this.pollStatus();
        }
      } catch (_) {}
    },

    onAgentEvent(ev) {
      if (window.mayaConversationStore) window.mayaConversationStore.handleAgentEvent(ev);
      if (ev.type === "ready") {
        this.s.ready = !!ev.value;
        if (ev.value) {
          this.s.error = "";
          this.pollStatus();
          if (window.mayaConversationStore) window.mayaConversationStore.syncFromServer();
        }
      }
      if (ev.type === "status") this.s.status = ev.value || this.s.status;
      if (ev.type === "error" && ev.text) this.s.error = ev.text;
      if (ev.type === "settings") this.initWebLLMBridge();
      if (ev.type === "webllm_unload" && window.mayaWebLLMBridge?.unload) {
        window.mayaWebLLMBridge.unload().then(() => this.refreshBridgeStatus());
      }
    },

    async pollStatus() {
      try {
        const r = await fetch("/api/voice/agent/status");
        if (!r.ok) return;
        const d = await r.json();
        this.s.ready = !!d.ready;
        this.s.status = d.status || "idle";
        if (window.mayaConversationStore && d.session_running !== undefined) {
          const store = Alpine.store("mayaConversation");
          if (store) {
            store.sessionOn = !!d.session_running;
            if (d.status) store.statusLabel = d.status;
          }
        }
        this.s.llmOk = !!d.llm_ok;
        this.s.llmReady = !!d.llm_ready;
        this.s.llmError = d.llm_error || "";
        this.s.llmModel = d.llm_model || "";
        this.s.llmProvider = d.llm_provider || "";
        this.s.llmHealth = d.llm_health || null;
        if (d.capabilities && typeof d.capabilities === "object") {
          this.s.capabilities = { ...this.s.capabilities, ...d.capabilities };
        }
        this.s.voiceAvailable = d.voice_available !== false;
        const owner = d.voice_owner;
        this.s.voiceOwnerName = owner?.speaker_name || owner?.context_id || "";
        this.refreshBridgeStatus();
        if (d.error) this.s.error = d.error;
      } catch (_) {}
    },

    async syncSettingsToSdk() {
      try {
        const r = await fetch("/api/voice/settings");
        if (!r.ok) return;
        const data = await r.json();
        const u = data.settings || {};
        const store = Alpine.store("mayaVoice");
        if (!store) return;
        if (!store.ready) await store.loadDefaults();
        const det = u.detection || {};
        const dict = u.dictation || {};
        const reas = u.reasoning || {};
        Object.assign(store.settings, {
          detection_mode: det.detection_mode || store.settings.detection_mode,
          vad_threshold: det.vad_threshold ?? store.settings.vad_threshold,
          vad_hangover_ms: det.vad_hangover_ms ?? store.settings.vad_hangover_ms,
          wispr_model: dict.wispr_model || store.settings.wispr_model,
          language: dict.language || store.settings.language,
          auto_punctuation: dict.auto_punctuation ?? store.settings.auto_punctuation,
          filler_removal: dict.filler_removal ?? store.settings.filler_removal,
          noise_suppression: dict.noise_suppression ?? store.settings.noise_suppression,
          reasoning_model: reas.reasoning_model || reas.model || store.settings.reasoning_model,
          persona: reas.persona || store.settings.persona,
        });
        store.persist();
      } catch (_) {}
    },
  }));
});
