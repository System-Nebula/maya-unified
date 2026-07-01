/** Conversation — voice session + server LLM chat when agent ready. */
document.addEventListener("alpine:init", () => {
  Alpine.data("mayaConversation", () => ({
    sessionOn: false,
    statusLabel: "idle",
    step: "listen",
    draft: "",
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

    async loadSettings() {
      try {
        const r = await fetch("/api/voice/settings");
        if (r.ok) {
          const data = await r.json();
          const w = data.settings?.reasoning?.webllm;
          this.useWebLLM = !!(data.settings?.reasoning?.provider === "webllm" && w?.enabled);
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
        if (v === "listening" || v === "hearing") this.step = "listen";
        else if (v === "transcribing") this.step = "detect";
        else if (v === "thinking") this.step = "reason";
        else if (v === "speaking") this.step = "maya";
        else if (v === "idle") {
          const last = this.turns[this.turns.length - 1];
          if (last && last._streaming) last._streaming = false;
        }
      }
      if (ev.type === "user" && ev.text) {
        const last = this.turns[this.turns.length - 1];
        if (last && last.role === "operator" && last.text === ev.text) return;
        this.turns.push({ role: "operator", text: ev.text });
      }
      if (ev.type === "ai" && ev.text) {
        const last = this.turns[this.turns.length - 1];
        if (last && last.role === "maya" && last._streaming) {
          const chunk = String(ev.text);
          if (last.text.endsWith(chunk)) return;
          last.text = last.text ? `${last.text} ${chunk}` : chunk;
        } else {
          this.turns.push({ role: "maya", text: ev.text, _streaming: true });
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
