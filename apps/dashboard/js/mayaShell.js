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
    llmError: "",
    llmModel: "",
    page: "",
    loadStarted: 0,

    label() {
      if (this.error) return "agent error";
      if (!this.ready) {
        if (this.status === "loading") return "loading models";
        return this.status || "connecting";
      }
      if (!this.llmOk) return "llm offline";
      return "agent ready";
    },

    chipClass() {
      if (this.error) return "error";
      if (this.ready && !this.llmOk) return "loading";
      if (this.ready) return "ready";
      return "loading";
    },

    hint() {
      if (this.error) return this.error.slice(0, 140);
      if (this.ready && !this.llmOk) {
        return (this.llmError || "Start LM Studio and load a model.").slice(0, 140);
      }
      if (!this.ready && this.loadStarted) {
        const s = Math.floor((Date.now() - this.loadStarted) / 1000);
        if (s > 30) return "First load downloads TTS weights — can take several minutes.";
        if (s > 10) return "Loading STT + TTS on GPU…";
      }
      if (this.ready && this.llmOk && this.llmModel) {
        return this.llmModel;
      }
      return "";
    },
  });

  Alpine.data("mayaShell", () => ({
    get s() { return Alpine.store("mayaShell"); },
    _unsub: null,
    _bound: false,

    init() {
      if (this._bound) return;
      this._bound = true;
      const path = window.location.pathname.replace(/\/$/, "") || "/";
      if (path === "/" || path === "/conversation") this.s.page = "dashboard";
      else if (path.startsWith("/settings")) this.s.page = "settings";
      else if (path.startsWith("/memory")) this.s.page = "memory";
      else if (path.startsWith("/experimental")) this.s.page = "experimental";
      this.s.loadStarted = Date.now();
      this.pollStatus();
      this._unsub = window.mayaAgentEvents.subscribe((ev) => this.onAgentEvent(ev));
      this.syncSettingsToSdk();
      setInterval(() => this.pollStatus(), 12000);
    },

    onAgentEvent(ev) {
      if (ev.type === "ready") {
        this.s.ready = !!ev.value;
        if (ev.value) {
          this.s.error = "";
          this.pollStatus();
        }
      }
      if (ev.type === "status") this.s.status = ev.value || this.s.status;
      if (ev.type === "error" && ev.text) this.s.error = ev.text;
    },

    async pollStatus() {
      try {
        const r = await fetch("/api/voice/agent/status");
        if (!r.ok) return;
        const d = await r.json();
        this.s.ready = !!d.ready;
        this.s.status = d.status || "idle";
        this.s.llmOk = !!d.llm_ok;
        this.s.llmError = d.llm_error || "";
        this.s.llmModel = d.llm_model || "";
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
