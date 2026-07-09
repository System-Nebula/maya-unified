/** Personality cards — import/export, edit, smart builder (qwen3 parity). */
document.addEventListener("alpine:init", () => {
  const API = "/api/voice/agent/personalities";

  Alpine.data("mayaPersonality", () => ({
    loading: true,
    busy: false,
    status: "",
    error: "",
    activeId: "",
    personalities: [],
    name: "",
    builderPrompt: "",
    creatorNotes: "—",
    promptPreview: "",
    card: {
      description: "",
      personality: "",
      scenario: "",
      first_mes: "",
      mes_example: "",
      system_prompt: "",
      post_history_instructions: "",
      tags: "",
    },

    async init() {
      await this.reload();
      this.loading = false;
    },

    async reload() {
      try {
        const r = await fetch(API);
        const d = await r.json();
        if (!d.ok) throw new Error(d.error || "load failed");
        this.personalities = d.personalities || [];
        this.activeId = d.active || "";
        if (!this.activeId && this.personalities.length) {
          this.activeId = this.personalities[0].id;
        }
        if (d.card) {
          this.applyDetail(d);
        } else if (this.activeId) {
          await this.loadActiveDetail();
        }
      } catch (e) {
        this.error = String(e.message || e);
      }
    },

    async loadActiveDetail() {
      if (!this.activeId) return;
      try {
        const r = await fetch(`${API}/export?id=${encodeURIComponent(this.activeId)}`);
        const d = await r.json();
        if (!d.ok || !d.export?.data) return;
        const card = d.export.data;
        this.applyDetail({
          card,
          creator_notes: card.creator_notes || "",
          system_prompt: card.system_prompt || "",
        });
      } catch (_) {
        /* export fallback is best-effort */
      }
    },

    applyDetail(d) {
      const c = d.card || {};
      this.name = c.name || this.personalities.find((p) => p.id === this.activeId)?.name || "";
      this.card.description = c.description || "";
      this.card.personality = c.personality || "";
      this.card.scenario = c.scenario || "";
      this.card.first_mes = c.first_mes || "";
      this.card.mes_example = c.mes_example || "";
      this.card.system_prompt = c.system_prompt || "";
      this.card.post_history_instructions = c.post_history_instructions || "";
      this.card.tags = Array.isArray(c.tags) ? c.tags.join(", ") : "";
      this.creatorNotes = (d.creator_notes || c.creator_notes || "").trim() || "—";
      this.promptPreview = d.system_prompt || d.prompt || c.system_prompt || "";
    },

    collectCard() {
      const tags = (this.card.tags || "").split(",").map((s) => s.trim()).filter(Boolean);
      return {
        name: (this.name || "").trim(),
        description: this.card.description || "",
        personality: this.card.personality || "",
        scenario: this.card.scenario || "",
        first_mes: this.card.first_mes || "",
        mes_example: this.card.mes_example || "",
        system_prompt: this.card.system_prompt || "",
        post_history_instructions: this.card.post_history_instructions || "",
        tags,
        alternate_greetings: [],
        creator_notes: this.creatorNotes === "—" ? "" : this.creatorNotes,
        creator: "",
        character_version: "1.0",
        extensions: {},
        character_book: null,
      };
    },

    async post(path, body) {
      const r = await fetch(`${API}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
      });
      return r.json();
    },

    async onSelectChange() {
      if (!this.activeId) return;
      this.busy = true;
      try {
        const d = await this.post("/activate", { id: this.activeId });
        if (d.ok) {
          this.applyDetail(d);
          this.status = "Activated";
          await this.syncSettingsPersonality();
        } else this.error = d.error || "activate failed";
      } finally {
        this.busy = false;
      }
    },

    async syncSettingsPersonality() {
      try {
        await fetch("/api/voice/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ settings: { personality: { active_id: this.activeId } } }),
        });
      } catch (_) {}
    },

    async saveNew() {
      const name = (this.name || "").trim();
      if (!name) { this.error = "Enter a preset name"; return; }
      this.busy = true;
      this.error = "";
      try {
        const d = await this.post("/save", { name, card: this.collectCard(), activate: true });
        if (d.ok) {
          this.applyDetail(d);
          this.activeId = d.active || this.activeId;
          if (d.personalities) this.personalities = d.personalities;
          this.status = "Saved";
          await this.syncSettingsPersonality();
        } else this.error = d.error || "save failed";
      } finally {
        this.busy = false;
      }
    },

    async updateSelected() {
      if (!this.activeId) { this.error = "Select a preset first"; return; }
      this.busy = true;
      try {
        const d = await this.post("/save", {
          id: this.activeId,
          name: (this.name || "").trim() || this.activeId,
          card: this.collectCard(),
          activate: true,
        });
        if (d.ok) {
          this.applyDetail(d);
          if (d.personalities) this.personalities = d.personalities;
          this.status = "Updated";
        } else this.error = d.error || "update failed";
      } finally {
        this.busy = false;
      }
    },

    async deleteSelected() {
      if (!this.activeId || !confirm("Delete this personality preset?")) return;
      this.busy = true;
      try {
        const d = await this.post("/delete", { id: this.activeId });
        if (d.ok) {
          this.personalities = d.personalities || [];
          this.activeId = d.active || "";
          this.applyDetail(d);
          this.status = "Deleted";
          await this.syncSettingsPersonality();
        } else this.error = d.error || "delete failed";
      } finally {
        this.busy = false;
      }
    },

    async buildCard() {
      const prompt = (this.builderPrompt || "").trim();
      if (!prompt) { this.error = "Describe your character first"; return; }
      this.busy = true;
      this.status = "Generating with LLM…";
      this.error = "";
      try {
        const d = await this.post("/build", { prompt });
        if (!d.ok) {
          this.error = d.error || "Generation failed — is LM Studio running?";
          this.status = "";
          return;
        }
        this.applyDetail(d);
        this.name = (d.card?.name || this.name || "").trim();
        if (!this.name) {
          this.status = "Generated — enter a name and Save.";
          return;
        }
        this.status = "Saving and activating…";
        const saved = await this.post("/save", {
          name: this.name,
          card: this.collectCard(),
          activate: true,
        });
        if (saved.ok) {
          this.applyDetail(saved);
          this.activeId = saved.active || this.activeId;
          if (saved.personalities) this.personalities = saved.personalities;
          this.status = `Saved and activated as "${this.name}"`;
          await this.syncSettingsPersonality();
        } else {
          this.error = saved.error || "Save failed after generation";
          this.status = "Generated — review fields, then Save.";
        }
      } finally {
        this.busy = false;
      }
    },

    triggerImport() {
      this.$refs.importFile?.click();
    },

    async onImport(ev) {
      const file = ev.target?.files?.[0];
      ev.target.value = "";
      if (!file) return;
      this.busy = true;
      try {
        let d;
        if (/\.png$/i.test(file.name) || file.type === "image/png") {
          const fd = new FormData();
          fd.append("file", file);
          const r = await fetch(`${API}/import-png`, { method: "POST", body: fd });
          d = await r.json();
        } else {
          const raw = JSON.parse(await file.text());
          d = await this.post("/import", raw);
        }
        if (d.ok) {
          this.applyDetail(d);
          if (d.personalities) this.personalities = d.personalities;
          this.activeId = d.active || this.activeId;
          this.status = "Imported";
          await this.syncSettingsPersonality();
        } else this.error = d.error || "Import failed";
      } catch {
        this.error = "Expected Character Card V2 JSON or SillyTavern PNG";
      } finally {
        this.busy = false;
      }
    },

    async exportSelected() {
      if (!this.activeId) return;
      try {
        const r = await fetch(`${API}/export?id=${encodeURIComponent(this.activeId)}`);
        const d = await r.json();
        if (!d.ok || !d.export) { this.error = d.error || "export failed"; return; }
        const blob = new Blob([JSON.stringify(d.export, null, 2)], { type: "application/json" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = (d.export.data?.name || this.activeId).replace(/[^\w.-]+/g, "_") + ".json";
        a.click();
        URL.revokeObjectURL(a.href);
      } catch (e) {
        this.error = String(e.message || e);
      }
    },
  }));
});
