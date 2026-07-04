/** Alpine panel — in-browser VRM avatar with TTS lip-sync + pop-out window. */
import { createVrmBus } from "/dashboard/js/mayaVrmBus.js";
import { DEFAULT_VRM_LOCAL } from "/dashboard/js/mayaVrmEngine.js";

const POPOUT_NAME = "maya-vrm-popout";
const POPOUT_FEATURES = "popup,width=420,height=560,left=120,top=80,resizable=yes";

document.addEventListener("alpine:init", () => {
  Alpine.data("mayaVrmViewer", () => ({
    enabled: true,
    model: "",
    lipSyncMode: "viseme",
    mouthGain: 6,
    mouthSmoothing: 0.5,
    lookAtCamera: true,
    cameraDistance: 1.8,
    idleEnabled: true,
    idleAnimation: "Idle.fbx",
    loading: false,
    loadError: "",
    speaking: false,
    poppedOut: false,
    modelLabel: "",
    moodLabel: "",
    _moodFromTurn: false,
    _moodReleaseTimer: null,
    _engine: null,
    _enginePromise: null,
    _specTimer: null,
    _unsub: null,
    _bus: null,
    _popout: null,

    get agentReady() {
      return Alpine.store("mayaShell")?.ready || false;
    },

    async init() {
      this._bus = createVrmBus();
      this._bus.on((msg) => {
        if (msg?.type === "popout-close") this.onPopoutClosed();
        if (msg?.type === "popout-ready" && this._popout && !this._popout.closed) {
          this.poppedOut = true;
          this._engine?.dispose();
          this._engine = null;
        }
      });
      await this.$nextTick();
      await this.loadSettings();
      this._unsub = window.mayaAgentEvents?.subscribe((ev) => this.onAgentEvent(ev));
      this._attachExistingPopout();
      if (this.enabled && !this.poppedOut) {
        await this.bootViewer();
      }
    },

    _attachExistingPopout() {
      try {
        const w = window.open("", POPOUT_NAME);
        if (!w || w.closed) return;
        const path = w.location?.pathname || "";
        if (!path.includes("/avatar/popout")) return;
        this._popout = w;
        this.poppedOut = true;
        const timer = setInterval(() => {
          if (!this._popout || this._popout.closed) {
            clearInterval(timer);
            this.onPopoutClosed();
          }
        }, 500);
      } catch (_) {}
    },

    destroy() {
      this.stopSpectrumPoll();
      if (this._unsub) this._unsub();
      this._engine?.dispose();
      this._engine = null;
      this._bus?.close();
    },

    async loadSettings() {
      try {
        const r = await fetch("/api/voice/settings");
        if (!r.ok) return;
        const data = await r.json();
        const vrm = data.settings?.vrm || {};
        this.enabled = vrm.enabled !== false;
        this.model = vrm.model || "";
        this.mouthGain = Number(vrm.mouth_gain ?? 6);
        this.mouthSmoothing = Number(vrm.mouth_smoothing ?? 0.5);
        this.lipSyncMode = vrm.lip_sync_mode === "amplitude" ? "amplitude" : "viseme";
        this.lookAtCamera = vrm.look_at_camera !== false;
        this.cameraDistance = Number(vrm.camera_distance ?? 1.8);
        this.idleEnabled = vrm.idle_enabled !== false;
        this.idleAnimation = vrm.idle_animation || "Idle.fbx";
        this.modelLabel = this.model ? this.model.replace(/^.*[/\\]/, "") : DEFAULT_VRM_LOCAL;
      } catch (_) {}
    },

    async ensureEngine() {
      if (this._engine) return this._engine;
      if (this._enginePromise) return this._enginePromise;
      this._enginePromise = (async () => {
        const { MayaVrmEngine } = await import("/dashboard/js/mayaVrmEngine.js");
        const canvas = this.$refs.vrmCanvas;
        if (!canvas) throw new Error("Canvas not ready");
        const engine = new MayaVrmEngine(canvas, {
          mouthGain: this.mouthGain,
          mouthSmoothing: this.mouthSmoothing,
          lipSyncMode: this.lipSyncMode,
          lookAtCamera: this.lookAtCamera,
          cameraDistance: this.cameraDistance,
          idleEnabled: this.idleEnabled,
          idleAnimation: this.idleAnimation,
        });
        engine.watchResize();
        engine.start();
        this._engine = engine;
        return engine;
      })();
      try {
        return await this._enginePromise;
      } finally {
        this._enginePromise = null;
      }
    },

    async bootViewer() {
      if (this.poppedOut) return;
      const canvas = this.$refs.vrmCanvas;
      if (!canvas) return;
      this.loading = true;
      this.loadError = "";
      try {
        const { resolveVrmUrl } = await import("/dashboard/js/mayaVrmEngine.js");
        const engine = await this.ensureEngine();
        engine.setMouthGain(this.mouthGain);
        engine.setMouthSmoothing(this.mouthSmoothing);
        engine.setLipSyncMode(this.lipSyncMode);
        engine.setIdleEnabled(this.idleEnabled);
        await engine.loadModel(resolveVrmUrl(this.model));
        const keys = engine.lipSyncInfo?.keys || {};
        this.lipSyncLabel = Object.entries(keys).map(([k, v]) => `${k}→${v}`).join(" ") || "no mouth expressions";
        this.moodLabel = engine.getMood?.() || "idle";
      } catch (e) {
        this.loadError = String(e.message || e);
      } finally {
        this.loading = false;
      }
    },

    openPopout() {
      if (this._popout && !this._popout.closed) {
        this._popout.focus();
        return;
      }
      this._popout = window.open("/avatar/popout", POPOUT_NAME, POPOUT_FEATURES);
      if (!this._popout) {
        this.loadError = "Pop-up blocked — allow pop-ups for this site.";
        return;
      }
      this.poppedOut = true;
      this._engine?.dispose();
      this._engine = null;
      this._bus.post({ type: "popout-open" });
      const timer = setInterval(() => {
        if (!this._popout || this._popout.closed) {
          clearInterval(timer);
          this.onPopoutClosed();
        }
      }, 500);
    },

    onPopoutClosed() {
      this.poppedOut = false;
      this._popout = null;
      if (this.enabled) this.bootViewer();
    },

    async reloadModel() {
      if (!this.enabled || this.poppedOut) return;
      await this.bootViewer();
    },

    async applyMood(mood, opts = {}) {
      const normalized = String(mood || "idle").toLowerCase();
      const ease = !!opts.ease;
      const payload = { type: "expression", mood: normalized, ease };
      if (this.poppedOut) {
        this._bus.post(payload);
        this.moodLabel = normalized;
        return;
      }
      const engine = this._engine || (await this.ensureEngine().catch(() => null));
      if (normalized === "idle" && ease) engine?.easeMoodToIdle?.();
      else engine?.setMood?.(normalized);
      this.moodLabel = engine?.getMood?.() || normalized;
    },

    releaseMoodAfterSpeech() {
      if (this._moodReleaseTimer) {
        clearTimeout(this._moodReleaseTimer);
        this._moodReleaseTimer = null;
      }
      if (!this._moodFromTurn) return;
      this._moodFromTurn = false;
      this.applyMood("idle", { ease: true });
    },

    scheduleMoodReleaseAfterSpeech() {
      if (!this._moodFromTurn) return;
      if (this._moodReleaseTimer) clearTimeout(this._moodReleaseTimer);
      this._moodReleaseTimer = setTimeout(() => this.releaseMoodAfterSpeech(), 400);
    },

    onMoodForTurn(mood) {
      const m = String(mood || "idle").toLowerCase();
      this._moodFromTurn = m !== "idle";
      this.applyMood(mood);
      if (this._moodReleaseTimer) {
        clearTimeout(this._moodReleaseTimer);
        this._moodReleaseTimer = null;
      }
      if (!this.speaking && this._moodFromTurn) {
        this._moodReleaseTimer = setTimeout(() => this.releaseMoodAfterSpeech(), 2200);
      }
    },

    async playAvatarAnimation(name, loop = false) {
      const payload = { type: "animation", name, loop: !!loop };
      if (this.poppedOut) {
        this._bus.post(payload);
        return;
      }
      const engine = this._engine || (await this.ensureEngine().catch(() => null));
      await engine?.playAnimation(name, { loop: !!loop });
    },

    onAgentEvent(ev) {
      if (ev.type === "avatar_expression" && ev.mood) {
        this.onMoodForTurn(ev.mood);
      }
      if (ev.type === "avatar_animation" && ev.name) {
        this.playAvatarAnimation(ev.name, !!ev.loop);
      }
      if (ev.type === "status") {
        const v = ev.value || "idle";
        if (v === "speaking") {
          if (this._moodReleaseTimer) {
            clearTimeout(this._moodReleaseTimer);
            this._moodReleaseTimer = null;
          }
          this.speaking = true;
          this.startSpectrumPoll();
        } else if (this.speaking && v !== "speaking") {
          this.speaking = false;
          this._bus.post({ type: "lip", level: 0, bands: [] });
          this.scheduleMoodReleaseAfterSpeech();
        }
      }
      if (ev.type === "audio_stop") {
        this.scheduleMoodReleaseAfterSpeech();
      }
      if (ev.type === "settings") {
        const v = ev.vrm || ev.unified?.vrm;
        if (!v) return;
        const prevModel = this.model;
        if (typeof v.enabled === "boolean") this.enabled = v.enabled;
        if (v.model != null) this.model = v.model;
        if (v.mouth_gain != null) this.mouthGain = Number(v.mouth_gain);
        if (v.mouth_smoothing != null) this.mouthSmoothing = Number(v.mouth_smoothing);
        if (v.lip_sync_mode != null) this.lipSyncMode = v.lip_sync_mode;
        if (v.look_at_camera != null) this.lookAtCamera = v.look_at_camera !== false;
        if (v.camera_distance != null) this.cameraDistance = Number(v.camera_distance);
        if (v.idle_enabled != null) this.idleEnabled = !!v.idle_enabled;
        if (v.idle_animation != null) this.idleAnimation = v.idle_animation;
        this.modelLabel = (this.model || DEFAULT_VRM_LOCAL).replace(/^.*[/\\]/, "");
        if (!this.poppedOut) {
          this._engine?.setMouthGain(this.mouthGain);
          this._engine?.setMouthSmoothing(this.mouthSmoothing);
          this._engine?.setLipSyncMode(this.lipSyncMode);
          this._engine?.setIdleEnabled(this.idleEnabled);
          if (v.idle_animation != null) this._engine?.setIdleAnimation(v.idle_animation);
          const modelChanged = v.model != null && String(v.model) !== String(prevModel);
          if (modelChanged || (v.model != null && !this._engine?.vrm)) {
            this.reloadModel();
          }
        }
        this._bus.post({ type: "settings", vrm: v });
      }
    },

    _relayLip(frame) {
      const level = Number(frame.level) || 0;
      this._bus.post({
        type: "lip",
        speaking: level > 0.002 || !!frame.speaking,
        level,
        bands: Array.isArray(frame.bands) ? frame.bands : [],
      });
    },

    _shouldStopSpectrumPoll(frame) {
      if (this.speaking) return false;
      const browser = window.mayaBrowserAudioOutput;
      if (browser?.isBrowserSink?.() && browser.isSpeaking?.()) return false;
      return (Number(frame?.level) || 0) < 0.002;
    },

    startSpectrumPoll() {
      if (this._specTimer || !this.enabled) return;
      this._specTimer = setInterval(async () => {
        const browser = window.mayaBrowserAudioOutput;
        let frame = { level: 0, bands: [] };
        if (browser?.isBrowserSink?.()) {
          frame = browser.getAudioFrame?.() || frame;
        } else {
          try {
            const r = await fetch("/api/voice/agent/spectrum");
            const d = await r.json();
            frame = { level: Number(d.level) || 0, bands: Array.isArray(d.bands) ? d.bands : [] };
          } catch (_) {}
        }
        if (this.poppedOut) {
          this._relayLip(frame);
        } else {
          this._engine?.setAudioFrame(frame);
        }
        if (this._shouldStopSpectrumPoll(frame)) {
          this.stopSpectrumPoll();
          if (!this.poppedOut) {
            this._engine?.setAudioFrame({ level: 0, bands: [] });
          }
          this.scheduleMoodReleaseAfterSpeech();
        }
      }, 50);
    },

    stopSpectrumPoll() {
      if (this._specTimer) {
        clearInterval(this._specTimer);
        this._specTimer = null;
      }
    },
  }));
});
