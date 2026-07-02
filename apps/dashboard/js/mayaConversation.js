/** Conversation — voice session + server LLM chat when agent ready. */
document.addEventListener("alpine:init", () => {
  Alpine.data("mayaConversation", () => ({
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
    _unsub: null,
    _bound: false,

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

    async loadSettings() {
      try {
        const r = await fetch("/api/voice/settings");
        if (r.ok) {
          const data = await r.json();
          this.useWebLLM = data.settings?.reasoning?.provider === "webllm";
        }
      } catch (_) {}
    },

    async init() {
      if (this._bound) return;
      this._bound = true;
      await this.loadSettings();
      this._unsub = window.mayaAgentEvents.subscribe((ev) => this.onAgentEvent(ev));
    },

    destroy() {
      if (this._unsub) {
        this._unsub();
        this._unsub = null;
      }
      this._bound = false;
    },

    onAgentEvent(ev) {
      if (ev.type === "status") {
        const v = ev.value || "idle";
        this.statusLabel = v;
        if (v === "listening" || v === "hearing") {
          this.step = "listen";
          if (this.ttsBusy) this.ttsBusy = false;
        } else if (v === "transcribing") this.step = "detect";
        else if (v === "thinking") this.step = "reason";
        else if (v === "speaking") this.step = "maya";
        else if (v === "idle") {
          const last = this.turns[this.turns.length - 1];
          if (last && last._streaming) last._streaming = false;
          if (this.ttsBusy) this.ttsBusy = false;
        }
      }
      if (ev.type === "error" && ev.text && this.ttsBusy) {
        this.ttsError = ev.text;
        this.ttsBusy = false;
      }
      if (ev.type === "tts_error" && ev.text) {
        this.ttsError = ev.text;
        this.ttsBusy = false;
      }
      if (ev.type === "user" && ev.text) {
        const last = this.turns[this.turns.length - 1];
        if (last && last.role === "operator" && last.text === ev.text) return;
        this.turns.push({ role: "operator", text: ev.text });
      }
      if (ev.type === "ai" && ev.text) {
        const last = this.turns[this.turns.length - 1];
        const chunk = String(ev.text);
        if (last && last.role === "maya" && last._streaming) {
          const cur = last.text || "";
          if (!chunk || cur.endsWith(chunk)) return;
          if (cur && chunk.startsWith(cur)) {
            last.text = chunk;
            return;
          }
          last.text = cur + chunk;
        } else {
          this.turns.push({ role: "maya", text: chunk, _streaming: true });
        }
      }
    },

    async startSession() {
      const r = await fetch("/api/voice/agent/start", { method: "POST" });
      const data = await r.json();
      if (data.ok) {
        this.sessionOn = true;
        this.$dispatch("maya-session-start");
      } else {
        this.turns.push({ role: "system", text: data.error || "Could not start session" });
      }
    },

    async stopSession() {
      await fetch("/api/voice/agent/stop", { method: "POST" });
      this.sessionOn = false;
      this.$dispatch("maya-session-stop");
    },

    async speakPreview() {
      const text = this.ttsDraft.trim();
      if (!text || this.ttsBusy || !this.agentReady) return;
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
      this.sending = true;
      this.draft = "";
      this.step = "reason";
      try {
        if (this.agentReady && this.llmOk) {
          const r = await fetch("/api/voice/agent/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text }),
          });
          const data = await r.json();
          if (!data.ok) {
            this.turns.push({ role: "system", text: data.error || "Chat failed" });
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
    },
  }));
});
