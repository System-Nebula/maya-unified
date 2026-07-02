document.addEventListener("alpine:init", () => {
  Alpine.data("mayaRoom", () => ({
    slug: "",
    room: {},
    joined: false,
    memberId: "",
    displayName: "Guest",
    messages: [],
    draft: "",
    sending: false,
    error: "",
    queuePos: 0,
    isActiveSpeaker: false,
    _es: null,
    _poll: null,

    init() {
      const parts = window.location.pathname.split("/");
      this.slug = parts[parts.length - 1] || "";
      this.loadInfo();
    },

    async loadInfo() {
      try {
        const r = await fetch(`/api/rooms/${this.slug}`);
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || "Room not found");
        this.room = d.room || {};
      } catch (e) {
        this.error = String(e.message || e);
      }
    },

    async join() {
      this.error = "";
      try {
        const r = await fetch(`/api/rooms/${this.slug}/join`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ display_name: this.displayName }),
          credentials: "include",
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || d.error || "Join failed");
        this.memberId = d.member_id;
        this.joined = true;
        await this.loadMessages();
        this.connectEvents();
        this._poll = setInterval(() => this.refreshQueue(), 5000);
      } catch (e) {
        this.error = String(e.message || e);
      }
    },

    connectEvents() {
      if (this._es) return;
      this._es = new EventSource(`/api/rooms/${this.slug}/events`);
      this._es.onmessage = (e) => {
        try {
          const ev = JSON.parse(e.data);
          if (ev.type === "user" || ev.type === "ai") {
            this.loadMessages();
          }
          if (ev.type === "queue_granted" && ev.member_id === this.memberId) {
            this.isActiveSpeaker = true;
          }
          if (ev.type === "queue_released") {
            this.isActiveSpeaker = false;
          }
        } catch (_) {}
      };
    },

    async loadMessages() {
      const r = await fetch(`/api/rooms/${this.slug}/messages`, { credentials: "include" });
      if (!r.ok) return;
      const d = await r.json();
      this.messages = d.messages || [];
    },

    async send() {
      const text = this.draft.trim();
      if (!text || this.sending) return;
      this.sending = true;
      this.draft = "";
      try {
        const r = await fetch(`/api/rooms/${this.slug}/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ text }),
        });
        const d = await r.json();
        if (!r.ok || !d.ok) throw new Error(d.error || d.detail || "Send failed");
        await this.loadMessages();
      } catch (e) {
        this.error = String(e.message || e);
      } finally {
        this.sending = false;
      }
    },

    async requestSpeak() {
      const r = await fetch(`/api/rooms/${this.slug}/queue/request`, {
        method: "POST",
        credentials: "include",
      });
      const d = await r.json();
      if (d.active_speaker_id === this.memberId) this.isActiveSpeaker = true;
      await this.refreshQueue();
    },

    async releaseSpeak() {
      await fetch(`/api/rooms/${this.slug}/queue/release`, {
        method: "POST",
        credentials: "include",
      });
      this.isActiveSpeaker = false;
      await this.refreshQueue();
    },

    async refreshQueue() {
      const r = await fetch(`/api/rooms/${this.slug}/queue`, { credentials: "include" });
      if (!r.ok) return;
      const d = await r.json();
      this.isActiveSpeaker = d.active_speaker_id === this.memberId;
      const idx = (d.queue || []).findIndex((q) => q.member_id === this.memberId);
      this.queuePos = idx >= 0 ? idx + 1 : 0;
    },
  }));
});
