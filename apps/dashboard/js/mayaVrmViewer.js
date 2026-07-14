/** Alpine panel — in-browser VRM avatar with TTS lip-sync + pop-out window. */
import { createVrmBus } from "/dashboard/js/mayaVrmBus.js";
import { DEFAULT_VRM_LOCAL } from "/dashboard/js/mayaVrmEngine.js";
import {
  applyVrmBackgroundAll,
  DEFAULT_VRM_BACKGROUND,
} from "/dashboard/js/mayaVrmBackground.js";

const POPOUT_NAME = "maya-vrm-popout";
const POPOUT_FEATURES = "popup,width=420,height=560,left=120,top=80,resizable=yes";
const IMMERSIVE_EVENT = "maya:toggle-immersive-avatar";

function _immersiveStorageKey() {
  const uid = window._mayaCurrentUser?.id || "anonymous";
  return `maya.conversation.immersive.v1.${uid}`;
}

function _vrmStore() {
  return typeof Alpine !== "undefined" ? Alpine.store("mayaVrm") : null;
}

function _bindStoreActions(viewer) {
  const s = _vrmStore();
  if (!s) return;
  s.toggleImmersive = (force) => viewer.toggleImmersive(force);
  s.openPopout = () => viewer.openPopout();
  s.closeImmersive = () => viewer.setImmersive(false);
}

document.addEventListener("alpine:init", () => {
  Alpine.store("mayaVrm", {
    immersive: false,
    enabled: true,
    speaking: false,
    loading: false,
    poppedOut: false,
    loadError: "",
    modelLabel: "",
    lipSyncLabel: "",
    lipSyncMode: "viseme",
    modelLoaded: false,
    showPlaceholder: false,
    avatarImage: "",
    placeholderCaption: "No avatar model",
    moodLabel: "",
    toggleImmersive() {},
    openPopout() {},
    closeImmersive() {},
  });

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
    idleVariants: [],
    idleVariantMinS: 10,
    idleVariantMaxS: 28,
    backgroundPreset: DEFAULT_VRM_BACKGROUND,
    backgroundImage: "",
    loading: false,
    loadError: "",
    speaking: false,
    poppedOut: false,
    immersive: false,
    modelLabel: "",
    lipSyncLabel: "",
    avatarImage: "",
    modelLoaded: false,
    placeholderHint: "",
    moodLabel: "",
    _moodFromTurn: false,
    _moodReleaseTimer: null,
    _engine: null,
    _enginePromise: null,
    _specTimer: null,
    _unsub: null,
    _bus: null,
    _popout: null,
    _onImmersiveToggle: null,

    get agentReady() {
      return Alpine.store("mayaShell")?.ready || false;
    },

    get agentError() {
      return Alpine.store("mayaShell")?.error || "";
    },

    get llmOk() {
      const shell = Alpine.store("mayaShell");
      return !!(shell?.llmReady || shell?.llmOk);
    },

    get textChatReady() {
      const shell = Alpine.store("mayaShell");
      return shell?.capabilities?.text_chat === true || shell?.llmReady === true;
    },

    get llmError() {
      return Alpine.store("mayaShell")?.llmError || "";
    },

    get showPlaceholder() {
      return !this.loading && !this.modelLoaded;
    },

    get placeholderCaption() {
      if (this.placeholderHint) return this.placeholderHint;
      if (this.loadError) return this.loadError;
      return "No avatar model";
    },

    _friendlyLoadError(msg) {
      const text = String(msg || "");
      if (/404|not found/i.test(text)) {
        return "No avatar model — upload a .vrm in Settings";
      }
      if (/canvas not ready/i.test(text)) return "";
      return text.length > 120 ? `${text.slice(0, 117)}…` : text;
    },

    _syncToStore() {
      const s = _vrmStore();
      if (!s) return;
      s.immersive = this.immersive;
      s.enabled = this.enabled;
      s.speaking = this.speaking;
      s.loading = this.loading;
      s.poppedOut = this.poppedOut;
      s.loadError = this.loadError;
      s.modelLabel = this.modelLabel;
      s.lipSyncLabel = this.lipSyncLabel;
      s.lipSyncMode = this.lipSyncMode;
      s.modelLoaded = this.modelLoaded;
      s.showPlaceholder = this.showPlaceholder;
      s.avatarImage = this.avatarImage;
      s.placeholderCaption = this.placeholderCaption;
      s.moodLabel = this.moodLabel;
    },

    _activeCanvas() {
      if (this.poppedOut) return null;
      if (this.immersive) {
        return (
          this.$refs.vrmImmersiveCanvas ||
          document.querySelector("[data-maya-vrm-canvas='immersive']")
        );
      }
      return document.querySelector("[data-maya-vrm-canvas='sidebar']");
    },

    _applyBackground() {
      applyVrmBackgroundAll(this.$el, {
        preset: this.backgroundPreset,
        image: this.backgroundImage,
      });
    },

    _persistImmersive() {
      try {
        sessionStorage.setItem(_immersiveStorageKey(), this.immersive ? "1" : "0");
      } catch (_) {}
    },

    _restoreImmersive() {
      try {
        this.immersive = sessionStorage.getItem(_immersiveStorageKey()) === "1";
      } catch (_) {
        this.immersive = false;
      }
    },

    async init() {
      this._bus = createVrmBus();
      this._bus.on((msg) => {
        if (msg?.type === "popout-close") this.onPopoutClosed();
        if (msg?.type === "popout-ready") {
          this.poppedOut = true;
          this._engine?.dispose();
          this._engine = null;
          this._syncToStore();
        }
      });
      _bindStoreActions(this);
      this._onImmersiveToggle = () => this.toggleImmersive();
      window.addEventListener(IMMERSIVE_EVENT, this._onImmersiveToggle);
      await this.$nextTick();
      await this.loadSettings();
      this._restoreImmersive();
      this._applyBackground();
      this._syncToStore();
      await this.$nextTick();
      this._unsub = window.mayaAgentEvents?.subscribe((ev) => this.onAgentEvent(ev));
      // Ask an existing popout to identify itself over BroadcastChannel. Calling
      // window.open("", name) here used to create an about:blank tab on every load.
      this._bus.post({ type: "popout-probe" });
      await new Promise((resolve) => setTimeout(resolve, 75));
      if (this.enabled && !this.poppedOut) {
        await this.bootViewer();
      }
    },

    destroy() {
      this.stopSpectrumPoll();
      if (this._unsub) this._unsub();
      if (this._onImmersiveToggle) {
        window.removeEventListener(IMMERSIVE_EVENT, this._onImmersiveToggle);
      }
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
        this.idleVariants = Array.isArray(vrm.idle_variants) ? [...vrm.idle_variants] : [];
        this.idleVariantMinS = Number(vrm.idle_variant_min_s ?? 10);
        this.idleVariantMaxS = Number(vrm.idle_variant_max_s ?? 28);
        this.backgroundPreset = vrm.background_preset || DEFAULT_VRM_BACKGROUND;
        this.backgroundImage = vrm.background_image || "";
        this.modelLabel = this.model ? this.model.replace(/^.*[/\\]/, "") : DEFAULT_VRM_LOCAL;
        this._applyBackground();
        this._syncToStore();
      } catch (_) {}
    },

    async ensureEngine() {
      if (this._engine) return this._engine;
      if (this._enginePromise) return this._enginePromise;
      this._enginePromise = (async () => {
        const { MayaVrmEngine } = await import("/dashboard/js/mayaVrmEngine.js");
        const canvas = this._activeCanvas();
        if (!canvas) throw new Error("Canvas not ready");
        const engine = new MayaVrmEngine(canvas, {
          mouthGain: this.mouthGain,
          mouthSmoothing: this.mouthSmoothing,
          lipSyncMode: this.lipSyncMode,
          lookAtCamera: this.lookAtCamera,
          cameraDistance: this.cameraDistance,
          frameProfile: this.immersive ? "immersive" : "default",
          idleEnabled: this.idleEnabled,
          idleAnimation: this.idleAnimation,
          idleVariants: this.idleVariants,
          idleVariantMinS: this.idleVariantMinS,
          idleVariantMaxS: this.idleVariantMaxS,
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
      const canvas = this._activeCanvas();
      if (!canvas) return;
      this.loading = true;
      this.loadError = "";
      this.placeholderHint = "";
      this._syncToStore();
      try {
        const { resolveVrmUrl } = await import("/dashboard/js/mayaVrmEngine.js");
        const engine = await this.ensureEngine();
        engine.setMouthGain(this.mouthGain);
        engine.setMouthSmoothing(this.mouthSmoothing);
        engine.setLipSyncMode(this.lipSyncMode);
        engine.setIdleEnabled(this.idleEnabled);
        engine.setIdleVariants(this.idleVariants);
        engine.setIdleVariantInterval(this.idleVariantMinS, this.idleVariantMaxS);
        await engine.loadModel(resolveVrmUrl(this.model));
        const keys = engine.lipSyncInfo?.keys || {};
        this.lipSyncLabel = Object.entries(keys).map(([k, v]) => `${k}→${v}`).join(" ") || "no mouth expressions";
        this.modelLoaded = true;
        this.placeholderHint = "";
        this.loadError = "";
        this.moodLabel = engine.getMood?.() || "idle";
        this._syncToStore();
      } catch (e) {
        this.modelLoaded = false;
        const friendly = this._friendlyLoadError(e.message || e);
        this.placeholderHint = friendly || "No avatar model";
        this.loadError = "";
      } finally {
        this.loading = false;
        this._syncToStore();
        this.$nextTick(() => window.dispatchEvent(new Event("resize")));
      }
    },

    async _relocateEngine(nextImmersive) {
      this._engine?.dispose();
      this._engine = null;
      this.immersive = nextImmersive;
      this._persistImmersive();
      this._syncToStore();
      await this.$nextTick();
      this._applyBackground();
      if (this.enabled && !this.poppedOut) {
        await this.bootViewer();
      }
      this.$nextTick(() => window.dispatchEvent(new Event("resize")));
    },

    async toggleImmersive(force) {
      if (this.poppedOut) return;
      const next = typeof force === "boolean" ? force : !this.immersive;
      if (next === this.immersive) return;
      await this._relocateEngine(next);
    },

    async setImmersive(value) {
      await this.toggleImmersive(!!value);
    },

    async openPopout() {
      if (this._popout && !this._popout.closed) {
        this._popout.focus();
        return;
      }
      if (this.immersive) {
        await this._relocateEngine(false);
      }
      this._popout = window.open("/avatar/popout", POPOUT_NAME, POPOUT_FEATURES);
      if (!this._popout) {
        this.loadError = "Pop-up blocked — allow pop-ups for this site.";
        this._syncToStore();
        return;
      }
      this.poppedOut = true;
      this._engine?.dispose();
      this._engine = null;
      this._syncToStore();
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
      this._syncToStore();
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
        this._syncToStore();
        return;
      }
      const engine = this._engine || (await this.ensureEngine().catch(() => null));
      if (normalized === "idle" && ease) engine?.easeMoodToIdle?.();
      else engine?.setMood?.(normalized);
      this.moodLabel = engine?.getMood?.() || normalized;
      this._syncToStore();
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
      if (ev.type === "ai" && ev.text) {
        this._bus.post({ type: "subtitle", text: ev.text, sender: "ai", final: !!ev.final });
      }
      if (ev.type === "status") {
        const v = ev.value || "idle";
        if (v === "speaking") {
          if (this._moodReleaseTimer) {
            clearTimeout(this._moodReleaseTimer);
            this._moodReleaseTimer = null;
          }
          this.speaking = true;
          this._syncToStore();
          this.startSpectrumPoll();
        } else if (this.speaking && v !== "speaking") {
          this.speaking = false;
          this._syncToStore();
          this._bus.post({ type: "lip", level: 0, bands: [] });
          this.scheduleMoodReleaseAfterSpeech();
        }
      }
      if (ev.type === "audio_stop") {
        this.speaking = false;
        this._syncToStore();
        this.stopSpectrumPoll();
        this._engine?.setAudioFrame({ speaking: false, level: 0, bands: [] });
        this._engine?.lipSync?.reset();
        this._bus.post({ type: "lip", speaking: false, level: 0, bands: [] });
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
        if (v.idle_variants != null) {
          this.idleVariants = Array.isArray(v.idle_variants) ? [...v.idle_variants] : [];
        }
        if (v.idle_variant_min_s != null) this.idleVariantMinS = Number(v.idle_variant_min_s);
        if (v.idle_variant_max_s != null) this.idleVariantMaxS = Number(v.idle_variant_max_s);
        if (v.background_preset != null) this.backgroundPreset = v.background_preset || DEFAULT_VRM_BACKGROUND;
        if (v.background_image != null) this.backgroundImage = v.background_image || "";
        this.modelLabel = (this.model || DEFAULT_VRM_LOCAL).replace(/^.*[/\\]/, "");
        this._applyBackground();
        if (!this.poppedOut) {
          this._engine?.setMouthGain(this.mouthGain);
          this._engine?.setMouthSmoothing(this.mouthSmoothing);
          this._engine?.setLipSyncMode(this.lipSyncMode);
          this._engine?.setIdleEnabled(this.idleEnabled);
          this._engine?.setIdleVariants(this.idleVariants);
          this._engine?.setIdleVariantInterval(this.idleVariantMinS, this.idleVariantMaxS);
          if (v.idle_animation != null) this._engine?.setIdleAnimation(v.idle_animation);
          const modelChanged = v.model != null && String(v.model) !== String(prevModel);
          if (modelChanged || (v.model != null && !this._engine?.vrm)) {
            this.reloadModel();
          }
        }
        this._syncToStore();
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
          this._relayLip(frame);
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

export { IMMERSIVE_EVENT };
