/** Animation manager — upload Mixamo clips, preview on VRM, set idle loop. */
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
    uploadName: "",
    uploadLabel: "",
    uploadDesc: "",
    dragOver: false,
    editingFile: null,
    editDraft: { label: "", description: "", tags: "", loop: false },
    savingEdit: false,
    _engine: null,
    _enginePromise: null,
    _unsub: null,
    _toastTimer: null,

    get agentReady() {
      return Alpine.store("mayaShell")?.ready || false;
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

    async loadSettings() {
      try {
        const r = await fetch("/api/voice/settings");
        if (!r.ok) return;
        const data = await r.json();
        const vrm = data.settings?.vrm || {};
        this.idleAnimation = vrm.idle_animation || "Idle.fbx";
        this.modelLabel = (vrm.model || "Yuki.vrm").replace(/^.*[/\\]/, "");
      } catch (_) {}
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

    isIdle(item) {
      return item?.file === this.idleAnimation;
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

    async setAsIdle(item) {
      this.error = "";
      try {
        const r = await fetch("/api/voice/settings");
        const data = await r.json();
        const settings = data.settings || {};
        settings.vrm = { ...(settings.vrm || {}), idle_animation: item.file, idle_enabled: true };
        const save = await fetch("/api/voice/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ settings }),
        });
        const saved = await save.json();
        if (!save.ok || saved.ok === false) {
          this.error = saved.error || saved.detail || "Could not save idle animation";
          return;
        }
        this.idleAnimation = item.file;
        await this._engine?.setIdleAnimation(item.file);
        this.showToast(`${item.label || item.file} is now the idle loop`);
      } catch (e) {
        this.error = String(e.message || e);
      }
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
        if (this.idleAnimation === item.file) this.idleAnimation = "Idle.fbx";
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

    async saveMeta(item, field, value) {
      try {
        const body = { file: item.file, [field]: value };
        const r = await fetch("/api/voice/agent/animation/meta", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const data = await r.json();
        if (data.catalog) this.catalog = data.catalog;
      } catch (_) {}
    },

    onAgentEvent(ev) {
      if (ev.type === "settings") {
        const vrm = ev.vrm || ev.unified?.vrm;
        if (vrm?.model != null || vrm?.idle_animation != null) {
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
