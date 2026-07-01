/** Memory explorer — curated facts, DB browse, session search (qwen3 parity). */
document.addEventListener("alpine:init", () => {
  Alpine.data("mayaMemoryPanel", () => ({
    loading: true,
    enabled: false,
    error: "",
    userEntries: [],
    memEntries: [],
    userUsage: "",
    memUsage: "",
    pending: [],
    cognitive: { total: 0, model: "", loaded: false },
    skills: [],
    skillDetail: "",
    skillDetailName: "",
    sessions: [],
    userAdd: "",
    memAdd: "",
    searchQuery: "",
    searchResults: [],
    db: "state",
    dbOffset: 0,
    dbLimit: 30,
    dbSessionId: "",
    dbScope: "",
    dbRows: [],
    dbColumns: [],
    dbTotal: 0,
    dbPageLabel: "",
    _unsub: null,

    get agentReady() {
      return Alpine.store("mayaShell")?.ready || false;
    },

    async init() {
      await this.refresh();
      this._unsub = window.mayaAgentEvents?.subscribe((ev) => this.onEvent(ev));
      this.loading = false;
    },

    destroy() {
      if (this._unsub) this._unsub();
    },

    onEvent(ev) {
      if (ev.type === "memory_updated" || ev.type === "memory_pending") this.refresh();
      if (ev.type === "ready" && ev.value) this.refresh();
    },

    api(path, opts) {
      return fetch("/api/voice/agent" + path, opts);
    },

    async refresh() {
      this.error = "";
      try {
        const r = await this.api("/memory");
        const d = await r.json();
        if (!d.ok && d.error) {
          this.error = d.error;
          return;
        }
        this.enabled = !!d.enabled;
        const c = d.curated || {};
        this.userEntries = c.user || [];
        this.memEntries = c.memory || [];
        this.userUsage = c.user_usage || "";
        this.memUsage = c.memory_usage || "";
        this.pending = d.pending || [];
        this.cognitive = d.cognitive || { total: 0, model: "", loaded: false };
        this.skills = d.skills || [];
        this.sessions = d.sessions || [];
        if (!this.enabled) return;
        await this.exploreDb(false);
      } catch (e) {
        this.error = String(e.message || e);
      }
    },

    async addEntry(target) {
      const content = (target === "user" ? this.userAdd : this.memAdd).trim();
      if (!content) return;
      const r = await this.api("/memory-edit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "add", target, content }),
      });
      const d = await r.json();
      if (!d.ok) {
        this.error = d.error || "Could not add entry";
        return;
      }
      if (target === "user") this.userAdd = "";
      else this.memAdd = "";
      await this.refresh();
    },

    async removeEntry(target, text) {
      await this.api("/memory-edit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "remove", target, old_text: text }),
      });
      await this.refresh();
    },

    async approvePending(id) {
      await this.api("/memory-approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id }),
      });
      await this.refresh();
    },

    async rejectPending(id) {
      await this.api("/memory-reject", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id }),
      });
      await this.refresh();
    },

    pendingLabel(item) {
      const p = item.payload || {};
      return `[${p.target || "memory"}/${p.action || "add"}] ${p.content || p.old_text || ""}`;
    },

    async loadSkill(name) {
      this.skillDetailName = name;
      this.skillDetail = "";
      try {
        const r = await this.api("/memory-skill?name=" + encodeURIComponent(name));
        const d = await r.json();
        if (d.ok) this.skillDetail = d.content || "";
      } catch (_) {}
    },

    async runSearch() {
      const q = this.searchQuery.trim();
      this.searchResults = [];
      if (!q) return;
      try {
        const r = await this.api("/session-search", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: q }),
        });
        const d = await r.json();
        this.searchResults = (d && d.results) || [];
      } catch (e) {
        this.error = String(e.message || e);
      }
    },

    onDbChange() {
      this.dbOffset = 0;
      this.exploreDb(true);
    },

    async exploreDb(resetOffset) {
      if (resetOffset) this.dbOffset = 0;
      if (!this.enabled) return;
      const params = new URLSearchParams({
        db: this.db,
        limit: String(this.dbLimit),
        offset: String(this.dbOffset),
      });
      if (this.db === "state" && this.dbSessionId) params.set("session_id", this.dbSessionId);
      if (this.db === "cognitive" && this.dbScope) params.set("scope", this.dbScope);
      try {
        const r = await this.api("/memory-explore?" + params);
        const data = await r.json();
        if (!data || !data.ok) return;
        if (data.db === "state") {
          this.dbColumns = ["id", "time", "session", "role", "content"];
          this.dbRows = (data.messages || []).map((m) => ({
            id: m.id,
            time: this.formatTs(m.ts),
            session: m.session_id,
            role: m.role,
            content: m.content,
          }));
        } else {
          this.dbColumns = ["id", "time", "scope", "imp", "content"];
          this.dbRows = (data.entries || []).map((e) => ({
            id: e.id,
            time: this.formatTs(e.ts),
            scope: e.scope,
            imp: Number(e.importance).toFixed(2),
            content: e.content + (e.superseded ? " (superseded)" : ""),
          }));
        }
        this.dbTotal = data.total || 0;
        const end = Math.min(this.dbTotal, this.dbOffset + this.dbRows.length);
        this.dbPageLabel = this.dbTotal
          ? `${this.dbOffset + 1}–${end} of ${this.dbTotal}`
          : "0 rows";
      } catch (_) {}
    },

    dbPrev() {
      this.dbOffset = Math.max(0, this.dbOffset - this.dbLimit);
      this.exploreDb(false);
    },

    dbNext() {
      if (this.dbOffset + this.dbLimit < this.dbTotal) {
        this.dbOffset += this.dbLimit;
        this.exploreDb(false);
      }
    },

    get dbHasPrev() {
      return this.dbOffset > 0;
    },

    get dbHasNext() {
      return this.dbOffset + this.dbLimit < this.dbTotal;
    },

    formatTs(ts) {
      if (!ts) return "";
      try {
        return new Date(ts * 1000).toLocaleString();
      } catch {
        return String(ts);
      }
    },

    searchResultLabel(r) {
      return (r.role === "user" ? "You: " : "Agent: ") + (r.content || "");
    },
  }));
});
