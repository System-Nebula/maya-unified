/** Memory explorer — curated facts, semantic DB, skills, session search. */
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
    cogEntries: [],
    cogTotal: 0,
    cogOffset: 0,
    cogLimit: 20,
    cogAdd: "",
    cogAddImportance: 0.6,
    cogEditingId: null,
    cogEditContent: "",
    cogEditImportance: 0.5,
    skills: [],
    skillDetail: "",
    skillDetailName: "",
    skillEditing: false,
    skillNewName: "",
    skillNewContent: "",
    sessions: [],
    userAdd: "",
    memAdd: "",
    curatedEditing: null,
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
    isAdmin: false,
    currentUserId: "",
    operators: [],
    exploreOperatorId: "",
    _unsub: null,

    get agentReady() {
      return Alpine.store("mayaShell")?.ready || false;
    },

    get cogPageLabel() {
      const end = Math.min(this.cogTotal, this.cogOffset + this.cogEntries.length);
      return this.cogTotal ? `${this.cogOffset + 1}–${end} of ${this.cogTotal}` : "0 rows";
    },

    get cogHasPrev() {
      return this.cogOffset > 0;
    },

    get cogHasNext() {
      return this.cogOffset + this.cogLimit < this.cogTotal;
    },

    async init() {
      try {
        const me = await fetch("/api/auth/me").then((r) => r.json());
        if (me.authenticated) {
          this.isAdmin = me.role === "admin";
          this.currentUserId = me.id || "";
          this.exploreOperatorId = me.id || "";
          if (this.isAdmin) await this.loadOperators();
        }
      } catch (_) {}
      await this.refresh();
      this._unsub = window.mayaAgentEvents?.subscribe((ev) => this.onEvent(ev));
      this.loading = false;
    },

    async loadOperators() {
      try {
        const res = await fetch("/api/admin/workspaces");
        if (!res.ok) return;
        const data = await res.json();
        this.operators = data.workspaces || [];
        if (!this.exploreOperatorId && this.operators.length) {
          this.exploreOperatorId = this.operators[0].id;
        }
      } catch (_) {}
    },

    onExploreOperatorChange() {
      this.dbOffset = 0;
      this.exploreDb(true);
    },

    destroy() {
      if (this._unsub) this._unsub();
    },

    onEvent(ev) {
      if (ev.type === "memory_updated" || ev.type === "memory_pending" || ev.type === "skill_updated") {
        this.refresh();
      }
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
        await this.loadCognitive(false);
        if (this.isAdmin) await this.exploreDb(false);
      } catch (e) {
        this.error = String(e.message || e);
      }
    },

    startCuratedEdit(target, text) {
      this.curatedEditing = { target, oldText: text, content: text };
    },

    cancelCuratedEdit() {
      this.curatedEditing = null;
    },

    async saveCuratedEdit() {
      const ed = this.curatedEditing;
      if (!ed) return;
      const content = (ed.content || "").trim();
      if (!content) return;
      const r = await this.api("/memory-edit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "replace",
          target: ed.target,
          old_text: ed.oldText,
          content,
        }),
      });
      const d = await r.json();
      if (!d.ok) {
        this.error = d.error || "Could not save entry";
        return;
      }
      this.curatedEditing = null;
      await this.refresh();
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

    async loadCognitive(resetOffset) {
      if (resetOffset) this.cogOffset = 0;
      try {
        const params = new URLSearchParams({
          limit: String(this.cogLimit),
          offset: String(this.cogOffset),
        });
        const r = await this.api("/memory-cognitive?" + params);
        const d = await r.json();
        if (!d.ok && d.error) return;
        this.cogEntries = d.entries || [];
        this.cogTotal = d.total || 0;
      } catch (_) {}
    },

    cogPrev() {
      this.cogOffset = Math.max(0, this.cogOffset - this.cogLimit);
      this.loadCognitive(false);
    },

    cogNext() {
      if (this.cogOffset + this.cogLimit < this.cogTotal) {
        this.cogOffset += this.cogLimit;
        this.loadCognitive(false);
      }
    },

    startCogEdit(entry) {
      this.cogEditingId = entry.id;
      this.cogEditContent = entry.content || "";
      this.cogEditImportance = entry.importance ?? 0.5;
    },

    cancelCogEdit() {
      this.cogEditingId = null;
    },

    async saveCogEdit() {
      if (!this.cogEditingId) return;
      const r = await this.api("/memory-cognitive-edit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "update",
          id: this.cogEditingId,
          content: this.cogEditContent.trim(),
          importance: Number(this.cogEditImportance),
        }),
      });
      const d = await r.json();
      if (!d.ok) {
        this.error = d.error || "Could not update semantic memory";
        return;
      }
      this.cogEditingId = null;
      await this.refresh();
    },

    async deleteCog(id) {
      await this.api("/memory-cognitive-edit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "delete", id }),
      });
      await this.refresh();
    },

    async addCognitive() {
      const content = this.cogAdd.trim();
      if (!content) return;
      const r = await this.api("/memory-cognitive-edit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "add",
          content,
          importance: Number(this.cogAddImportance),
        }),
      });
      const d = await r.json();
      if (!d.ok) {
        this.error = d.error || "Could not add semantic memory";
        return;
      }
      this.cogAdd = "";
      await this.refresh();
    },

    async loadSkill(name) {
      this.skillDetailName = name;
      this.skillDetail = "";
      this.skillEditing = false;
      try {
        const r = await this.api("/memory-skill?name=" + encodeURIComponent(name));
        const d = await r.json();
        if (d.ok) this.skillDetail = d.content || "";
      } catch (_) {}
    },

    startSkillEdit() {
      this.skillEditing = true;
    },

    cancelSkillEdit() {
      this.skillEditing = false;
    },

    async saveSkill() {
      const creating = !!this.skillNewName.trim();
      const name = (creating ? this.skillNewName : this.skillDetailName).trim();
      const content = (creating ? this.skillNewContent : this.skillDetail).trim();
      if (!name || !content) return;
      const r = await this.api("/memory-skill-edit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "write", name, content }),
      });
      const d = await r.json();
      if (!d.ok) {
        this.error = d.error || "Could not save skill";
        return;
      }
      this.skillEditing = false;
      this.skillNewName = "";
      this.skillNewContent = "";
      await this.refresh();
      if (name) await this.loadSkill(name);
    },

    async deleteSkill(name) {
      const n = (name || this.skillDetailName).trim();
      if (!n) return;
      await this.api("/memory-skill-edit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "delete", name: n }),
      });
      this.skillDetail = "";
      this.skillDetailName = "";
      this.skillEditing = false;
      await this.refresh();
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
      if (this.isAdmin && this.exploreOperatorId) {
        params.set("operator_id", this.exploreOperatorId);
      }
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
          this.dbColumns = ["id", "time", "scope", "imp", "content", "actions"];
          this.dbRows = (data.entries || []).map((e) => ({
            id: e.id,
            time: this.formatTs(e.ts),
            scope: e.scope,
            imp: Number(e.importance).toFixed(2),
            content: e.content + (e.superseded ? " (superseded)" : ""),
            rawContent: e.content,
            importance: e.importance,
          }));
        }
        this.dbTotal = data.total || 0;
        const end = Math.min(this.dbTotal, this.dbOffset + this.dbRows.length);
        this.dbPageLabel = this.dbTotal
          ? `${this.dbOffset + 1}–${end} of ${this.dbTotal}`
          : "0 rows";
      } catch (_) {}
    },

    async adminDeleteCog(id) {
      await this.deleteCog(id);
      await this.exploreDb(false);
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
