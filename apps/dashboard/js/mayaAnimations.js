/** Animation manager — upload Mixamo clips, preview on VRM, idle pool + gestures. */
const ANIM_DRAG_MIME = "application/x-maya-anim-file";

document.addEventListener("alpine:init", () => {
  Alpine.data("mayaAnimations", () => ({
    catalog: [],
    catalogLoading: false,
    previewLoading: false,
    previewReady: false,
    uploading: false,
    playing: "",
    error: "",
    toast: "",
    modelLabel: "",
    idleAnimation: "Idle.fbx",
    idleVariants: [],
    idleVariantMinS: 10,
    idleVariantMaxS: 28,
    uploadName: "",
    uploadLabel: "",
    uploadDesc: "",
    dragOver: false,
    idleDragHover: false,
    idleDragIdx: null,
    editingFile: null,
    editDraft: { label: "", description: "", tags: "", loop: false },
    savingEdit: false,
    _engine: null,
    _enginePromise: null,
    _unsub: null,
    _toastTimer: null,
    _savingIdle: false,

    get agentReady() {
      return Alpine.store("mayaShell")?.ready || false;
    },

    get idleClips() {
      const clips = [];
      const base = String(this.idleAnimation || "").trim();
      if (base) clips.push(base);
      for (const file of this.idleVariants || []) {
        if (file && file !== base && !clips.includes(file)) clips.push(file);
      }
      return clips;
    },

    get libraryItems() {
      const inIdle = new Set(this.idleClips);
      return (this.catalog || []).filter((item) => !inIdle.has(item.file));
    },

    async init() {
      await this.$nextTick();
      await this.loadSettings();
      await Promise.all([this.loadCatalog(), this.bootPreview()]);
      this._unsub = window.mayaAgentEvents?.subscribe((ev) => this.onAgentEvent(ev));
    },

    destroy() {
      if (this._unsub) this._unsub();
      this._engine?.dispose();
      this._engine = null;
    },

    showToast(msg) {
      this.toast = msg;
      clearTimeout(this._toastTimer);
      this._toastTimer = setTimeout(() => {
        this.toast = "";
      }, 3200);
    },

    catalogLabel(file) {
      const item = this.catalog.find((c) => c.file === file);
      return item?.label || String(file || "").replace(/\.[^.]+$/, "").replace(/[_-]/g, " ");
    },

    async loadSettings() {
      try {
        const r = await fetch("/api/voice/settings");
        if (!r.ok) return;
        const data = await r.json();
        const vrm = data.settings?.vrm || {};
        this.idleAnimation = vrm.idle_animation || "Idle.fbx";
        this.idleVariants = Array.isArray(vrm.idle_variants) ? [...vrm.idle_variants] : [];
        this.idleVariantMinS = Number(vrm.idle_variant_min_s ?? 10);
        this.idleVariantMaxS = Number(vrm.idle_variant_max_s ?? 28);
        this.modelLabel = (vrm.model || "Yuki.vrm").replace(/^.*[/\\]/, "");
        this._applyIdleToEngine();
      } catch (_) {}
    },

    _applyIdleToEngine() {
      const engine = this._engine;
      if (!engine) return;
      engine.setIdleVariants(this.idleVariants);
      engine.setIdleVariantInterval(this.idleVariantMinS, this.idleVariantMaxS);
    },

    async saveIdleSettings() {
      if (this._savingIdle) return;
      this._savingIdle = true;
      this.error = "";
      try {
        const r = await fetch("/api/voice/settings");
        const data = await r.json();
        const settings = data.settings || {};
        settings.vrm = {
          ...(settings.vrm || {}),
          idle_animation: this.idleAnimation,
          idle_variants: [...this.idleVariants],
          idle_enabled: true,
          idle_variant_min_s: this.idleVariantMinS,
          idle_variant_max_s: this.idleVariantMaxS,
        };
        const save = await fetch("/api/voice/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ settings }),
        });
        const saved = await save.json();
        if (!save.ok || saved.ok === false) {
          this.error = saved.error || saved.detail || "Could not save idle pool";
          return;
        }
        await this._engine?.setIdleAnimation(this.idleAnimation);
        this._applyIdleToEngine();
      } catch (e) {
        this.error = String(e.message || e);
      } finally {
        this._savingIdle = false;
      }
    },

    async _setIdleClips(clips, toastMsg) {
      const ordered = (clips || []).filter(Boolean);
      this.idleAnimation = ordered[0] || this.idleAnimation || "Idle.fbx";
      this.idleVariants = ordered.slice(1);
      await this.saveIdleSettings();
      if (toastMsg) this.showToast(toastMsg);
    },

    async addToIdle(file) {
      const name = String(file || "").trim();
      if (!name) return;
      if (this.idleClips.includes(name)) return;
      const next = [...this.idleClips, name];
      await this._setIdleClips(next, `${this.catalogLabel(name)} added to idle pool`);
    },

    async removeFromIdle(file) {
      const name = String(file || "").trim();
      const next = this.idleClips.filter((f) => f !== name);
      if (!next.length) {
        this.error = "Keep at least one default idle clip in the pool";
        return;
      }
      await this._setIdleClips(next, `${this.catalogLabel(name)} removed from idle pool`);
    },

    onLibraryDragStart(ev, item) {
      if (!item?.file) return;
      ev.dataTransfer.setData(ANIM_DRAG_MIME, item.file);
      ev.dataTransfer.setData("text/plain", item.file);
      ev.dataTransfer.effectAllowed = "move";
    },

    onIdleDragStart(ev, idx) {
      this.idleDragIdx = idx;
      const file = this.idleClips[idx];
      if (!file) return;
      ev.dataTransfer.setData(ANIM_DRAG_MIME, file);
      ev.dataTransfer.setData("text/plain", file);
      ev.dataTransfer.effectAllowed = "move";
    },

    onIdleDragEnd() {
      this.idleDragIdx = null;
      this.idleDragHover = false;
    },

    onIdleDragOver(ev, idx) {
      ev.dataTransfer.dropEffect = "move";
      if (this.idleDragIdx == null || this.idleDragIdx === idx) return;
      const clips = [...this.idleClips];
      const [moved] = clips.splice(this.idleDragIdx, 1);
      clips.splice(idx, 0, moved);
      this.idleDragIdx = idx;
      this.idleAnimation = clips[0] || this.idleAnimation;
      this.idleVariants = clips.slice(1);
    },

    async onIdleDrop(ev, idx) {
      this.idleDragHover = false;
      const file = String(
        ev.dataTransfer.getData(ANIM_DRAG_MIME) || ev.dataTransfer.getData("text/plain") || "",
      ).trim();
      const wasInternal = this.idleDragIdx != null;
      this.idleDragIdx = null;
      if (!file) return;
      if (wasInternal && this.idleClips.includes(file)) {
        await this._setIdleClips([...this.idleClips], "Idle order updated");
        return;
      }
      let clips = [...this.idleClips];
      const existing = clips.indexOf(file);
      if (existing >= 0) clips.splice(existing, 1);
      const insertAt = Number.isFinite(idx) ? Math.max(0, Math.min(idx, clips.length)) : clips.length;
      clips.splice(insertAt, 0, file);
      await this._setIdleClips(clips, `${this.catalogLabel(file)} moved in idle pool`);
    },

    async onDropToIdle(ev) {
      this.idleDragHover = false;
      const file = String(
        ev.dataTransfer.getData(ANIM_DRAG_MIME) || ev.dataTransfer.getData("text/plain") || "",
      ).trim();
      if (!file) return;
      if (this.idleClips.includes(file)) return;
      await this.addToIdle(file);
    },

    async loadCatalog() {
      this.catalogLoading = true;
      this.error = "";
      try {
        const r = await fetch("/api/voice/agent/animations", { credentials: "same-origin" });
        if (!r.ok) throw new Error(`Could not list animations (HTTP ${r.status})`);
        const data = await r.json();
        this.catalog = data.catalog || (data.animations || []).map((f) => ({
          file: f,
          label: f.replace(/\.[^.]+$/, "").replace(/[_-]/g, " "),
          description: "",
          tags: [],
          loop: false,
        }));
      } catch (e) {
        this.error = String(e.message || e);
      } finally {
        this.catalogLoading = false;
      }
    },

    async loadPreviewModel() {
      const { resolveVrmUrl } = await import("/dashboard/js/mayaVrmEngine.js");
      const r = await fetch("/api/voice/settings", { credentials: "same-origin" });
      const data = r.ok ? await r.json() : {};
      const vrm = data.settings?.vrm || {};
      const model = vrm.model || "Yuki.vrm";
      this.modelLabel = model.replace(/^.*[/\\]/, "");
      if (vrm.idle_animation) this.idleAnimation = vrm.idle_animation;
      if (Array.isArray(vrm.idle_variants)) this.idleVariants = [...vrm.idle_variants];
      return resolveVrmUrl(model);
    },

    async ensureEngine() {
      if (this._engine) return this._engine;
      if (this._enginePromise) return this._enginePromise;
      this._enginePromise = (async () => {
        const { MayaVrmEngine } = await import("/dashboard/js/mayaVrmEngine.js");
        const canvas = this.$refs.previewCanvas;
        if (!canvas) throw new Error("Preview canvas not ready — refresh the page");
        const engine = new MayaVrmEngine(canvas, {
          lookAtCamera: true,
          cameraDistance: 1.75,
          idleEnabled: true,
          idleAnimation: this.idleAnimation,
          idleVariants: this.idleVariants,
          idleVariantMinS: this.idleVariantMinS,
          idleVariantMaxS: this.idleVariantMaxS,
        });
        engine.watchResize();
        engine.start();
        const modelUrl = await this.loadPreviewModel();
        await engine.loadModel(modelUrl);
        this._engine = engine;
        this.previewReady = true;
        return engine;
      })();
      try {
        return await this._enginePromise;
      } catch (e) {
        this._enginePromise = null;
        throw e;
      }
    },

    async bootPreview() {
      this.previewLoading = true;
      this.previewReady = false;
      this.error = "";
      try {
        await this.ensureEngine();
      } catch (e) {
        this.error = `Avatar preview failed: ${e.message || e}`;
        this.previewReady = false;
      } finally {
        this.previewLoading = false;
      }
    },

    async reloadPreview() {
      this._engine?.dispose();
      this._engine = null;
      this._enginePromise = null;
      await this.bootPreview();
    },

    async playItem(item, loop = null) {
      if (!this.previewReady) {
        this.error = "Wait for the avatar preview to finish loading";
        return;
      }
      const engine = await this.ensureEngine();
      if (!engine) return;
      const useLoop = loop != null ? loop : !!item.loop;
      this.playing = item.file;
      const ok = await engine.playAnimation(item.file, { loop: useLoop });
      if (!ok) {
        this.error = `Could not play ${item.file} — is it a valid Mixamo FBX?`;
        this.playing = "";
        return;
      }
      if (!useLoop) {
        setTimeout(() => {
          if (this.playing === item.file) this.playing = "";
        }, 8000);
      }
    },

    async stopPlayback() {
      this._engine?.stopGesture();
      this.playing = "";
    },

    onDrop(ev) {
      ev.preventDefault();
      this.dragOver = false;
      const file = ev.dataTransfer?.files?.[0];
      if (file) this.uploadFile(file);
    },

    onFilePick(ev) {
      const file = ev.target?.files?.[0];
      if (file) this.uploadFile(file);
      ev.target.value = "";
    },

    async uploadFile(file) {
      if (this.uploading) return;
      const ext = (file.name || "").split(".").pop()?.toLowerCase();
      if (!["fbx", "vrma"].includes(ext)) {
        this.error = "Use a Mixamo .fbx file (or .vrma)";
        return;
      }
      const fd = new FormData();
      fd.append("file", file);
      if (this.uploadName.trim()) fd.append("name", this.uploadName.trim());
      if (this.uploadLabel.trim()) fd.append("label", this.uploadLabel.trim());
      if (this.uploadDesc.trim()) fd.append("description", this.uploadDesc.trim());
      this.uploading = true;
      this.error = "";
      try {
        const r = await fetch("/api/voice/agent/upload-animation", {
          method: "POST",
          body: fd,
          credentials: "same-origin",
        });
        let data = {};
        const raw = await r.text();
        try {
          data = raw ? JSON.parse(raw) : {};
        } catch (_) {
          this.error = raw?.slice(0, 200) || `Upload failed (HTTP ${r.status})`;
          return;
        }
        if (!r.ok || !data.ok) {
          this.error = data.error || data.detail || `Upload failed (HTTP ${r.status})`;
          return;
        }
        this.catalog = data.catalog || this.catalog;
        this.uploadName = "";
        this.uploadLabel = "";
        this.uploadDesc = "";
        this.showToast(`Uploaded ${data.file}`);
        if (!this.previewReady) await this.bootPreview();
        const added = this.catalog.find((c) => c.file === data.file);
        if (added) await this.playItem(added);
      } catch (e) {
        this.error = String(e.message || e);
      } finally {
        this.uploading = false;
      }
    },

    async deleteItem(item) {
      if (!confirm(`Delete ${item.file}?`)) return;
      this.error = "";
      try {
        const r = await fetch(`/api/voice/agent/animation?name=${encodeURIComponent(item.file)}`, {
          method: "DELETE",
        });
        const data = await r.json();
        if (!r.ok || !data.ok) {
          this.error = data.detail || data.error || "Delete failed";
          return;
        }
        this.catalog = data.catalog || [];
        if (this.playing === item.file) this.playing = "";
        const nextClips = this.idleClips.filter((f) => f !== item.file);
        if (nextClips.length !== this.idleClips.length) {
          if (!nextClips.length) {
            this.idleAnimation = "Idle.fbx";
            this.idleVariants = [];
          } else {
            await this._setIdleClips(nextClips);
          }
        }
        this.showToast(`Deleted ${item.file}`);
      } catch (e) {
        this.error = String(e.message || e);
      }
    },

    startEdit(item) {
      this.editingFile = item.file;
      this.editDraft = {
        label: item.label || "",
        description: item.description || "",
        tags: (item.tags || []).join(", "),
        loop: !!item.loop,
      };
    },

    cancelEdit() {
      this.editingFile = null;
    },

    async saveEdit(item) {
      if (this.savingEdit) return;
      this.savingEdit = true;
      this.error = "";
      const tags = String(this.editDraft.tags || "")
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      try {
        const r = await fetch("/api/voice/agent/animation/meta", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({
            file: item.file,
            label: String(this.editDraft.label || "").trim(),
            description: String(this.editDraft.description || "").trim(),
            tags,
            loop: !!this.editDraft.loop,
          }),
        });
        const data = await r.json();
        if (!r.ok || !data.ok) {
          this.error = data.detail || data.error || "Could not save";
          return;
        }
        if (data.catalog) this.catalog = data.catalog;
        this.editingFile = null;
        this.showToast(`Saved ${item.file}`);
      } catch (e) {
        this.error = String(e.message || e);
      } finally {
        this.savingEdit = false;
      }
    },

    onAgentEvent(ev) {
      if (ev.type === "settings") {
        const vrm = ev.vrm || ev.unified?.vrm;
        if (vrm?.model != null || vrm?.idle_animation != null || vrm?.idle_variants != null) {
          this.loadSettings().then(() => {
            if (this.previewReady) this.reloadPreview();
          });
        }
      }
      if (ev.type === "avatar_animation" && ev.name) {
        const item = this.catalog.find((c) => c.file === ev.name) || {
          file: ev.name,
          label: ev.name,
          loop: !!ev.loop,
        };
        this.playItem(item, !!ev.loop);
      }
    },
  }));
});
