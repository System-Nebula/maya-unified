/** Comprehensive settings UI — GET/POST /api/voice/settings + operator account */

function _detailedStorageKey() {
  const uid = window._mayaCurrentUser?.id || "anonymous";
  return `maya.conversation.detailed.v1.${uid}`;
}

document.addEventListener("alpine:init", () => {
  const AVATAR_COLOURS = [
    "#0a84ff", "#30d158", "#ff9f0a", "#ff453a",
    "#bf5af2", "#32ade6", "#ffd60a", "#ff6961",
    "#5e5ce6", "#64d2ff",
  ];

  Alpine.data("mayaSettings", () => ({
    tab: "account",
    filter: "",
    saved: false,
    error: "",
    warn: "",
    loading: true,
    agentReady: false,
    currentVoice: "",
    loadedTtsModel: "",
    ttsReloading: false,
    ttsStatus: "",
    health: null,
    healthTesting: false,
    imagineHealth: null,
    imagineHealthTesting: false,
    voiceUploadName: "",
    vrmUploadName: "",
    vrmBgUploadName: "",
    voiceUploadBusy: false,
    llmModelsLoading: false,
    llmModelsHint: "",
    _llmFetchTimer: null,
    _saveTimer: null,
    _voiceUiReady: false,
    _voiceFile: "",

    user: { id: "", username: "", display_name: "", role: "operator", avatar_color: "#0a84ff" },
    colours: AVATAR_COLOURS,
    accountSaving: false,
    savedId: false,
    errId: "",
    savedPw: false,
    errPw: "",
    clearedPrefs: false,
    newPw: "",
    confirmPw: "",
    conversationDetailed: true,

    catalog: {
      eq_presets: [],
      voices: [],
      vrm_models: [],
      vrm_backgrounds: [],
      animations: [],
      barge_modes: ["smart", "instant", "off"],
      delivery_modes: ["full", "hybrid", "off"],
      tts_modes: ["clone", "custom"],
      whisper_models: [],
      compute_types: ["float16", "int8", "float32"],
      stt_devices: ["cuda", "cpu"],
      speakers: [],
      detection_modes: ["vad", "push_to_talk", "continuous"],
      wispr_models: [],
      reasoning_models: [],
      languages: [],
      llm_models: [],
      litellm_models: [],
      remark_vision_models: [],
      webllm_models: [],
      clone_models: [],
      custom_tts_models: [],
      tts_languages: [],
      personas: ["maya", "operator", "assistant", "technical"],
    },
    s: {
      audio: { output_sink: "browser", output_volume: 1, eq_enabled: true, eq_preset: "off", aec_enabled: true },
      detection: {
        barge_mode: "smart", barge_in: true, vad_aggressiveness: 2,
        silence_ms: 500, min_speech_ms: 250, detection_mode: "vad",
        vad_threshold: 0.02, vad_hangover_ms: 600,
      },
      dictation: {
        whisper_model: "small.en", language: "en", device: "cuda", compute_type: "float16",
        wispr_model: "wispr-flow-1", auto_punctuation: true, filler_removal: true, noise_suppression: true,
      },
      voice: {
        ref_audio: "voices/ref.wav", ref_text: "", speaker: "aiden",
        clone_model: "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        custom_model: "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        language: "English", temperature: 0.7, top_k: 40, seed: 1234, warmup: false, device: "cuda",
      },
      runtime: { orchestrator: true, web_tools: true },
      reasoning: {
        provider: "lm_studio", base_url: "http://localhost:1234/v1", api_key: "lm-studio",
        model: "local-model", temperature: 0.6, max_tokens: 220, top_p: 0.9,
        disable_thinking: true, reasoning_model: "maya-reason-mini", persona: "maya",
        litellm: { mode: "sdk", model: "gemini/gemini-2.0-flash" },
        webllm: { enabled: false, model_id: "Llama-3.1-8B-Instruct-q4f16_1-MLC", use_for: ["conversation"] },
      },
      personality: { active_id: "" },
      memory: { enabled: true, write_approval: false, cognitive_enabled: true, prefetch: true },
      tools: { enabled: true, mode: "auto", max_rounds: 3, mcp_enabled: true },
      delivery: { tts_mode: "clone", delivery: "full", auto_instruct: true, xvec_only: true, instruct: "" },
      vts: {
        enabled: false, host: "127.0.0.1", port: 8001,
        expressions: true, auto_express: true, mouth_gain: 6, mouth_smoothing: 0.5, mouth_fps: 60,
      },
      vrm: {
        enabled: true, model: "Yuki.vrm", lip_sync_mode: "viseme",
        mouth_gain: 6, mouth_smoothing: 0.5, look_at_camera: true, camera_distance: 1.8,
        idle_enabled: true, idle_animation: "Idle.fbx", idle_variants: [],
        idle_variant_min_s: 10, idle_variant_max_s: 28,
        background_preset: "default", background_image: "",
      },
      imagine: { enabled: false, comfyui_url: "http://127.0.0.1:3030", default_model: "zit", remark_enabled: true, remark_vision_model: "openrouter/minimax/minimax-m3", director_enabled: true, director_max_iterations: 3, director_multi_critic: true, critique_vision_model: "" },
      discord: {
        enabled: false, token: "", guild_id: "", auto_reply: true, attach_voice: true,
        music_volume: 0.85,
        default_voice_channel: "", voice_channel_aliases: {},
        youtube_cookies_browser: "", youtube_cookies_file: "",
      },
      platform: { database_url: "", otel_enabled: false },
    },
    sectionGroups: [
      {
        title: "Account",
        items: [
          { id: "account", label: "Profile", hint: "Identity · password" },
        ],
      },
      {
        title: "Engine",
        items: [
          { id: "audio", label: "Audio", hint: "Volume · EQ · AEC" },
          { id: "detection", label: "Detection", hint: "VAD · barge-in" },
        ],
      },
      {
        title: "Voice",
        items: [
          { id: "voice", label: "Voice", hint: "Clone · speaker" },
          { id: "delivery", label: "Delivery", hint: "Flow · instruct" },
          { id: "expressions", label: "Expressions", hint: "VRM · VTube Studio" },
        ],
      },
      {
        title: "Models",
        items: [
          { id: "dictation", label: "Dictation", hint: "Whisper · Wispr" },
          { id: "reasoning", label: "Reasoning", hint: "LLM providers" },
        ],
      },
      {
        title: "Agent",
        items: [
          { id: "personality", label: "Personality", hint: "Character cards" },
          { id: "memory", label: "Memory", hint: "Recall · approval" },
          { id: "tools", label: "Tools", hint: "Web · MCP" },
        ],
      },
      {
        title: "Connect",
        items: [
          { id: "discord", label: "Discord", hint: "Bot · music" },
          { id: "imagine", label: "Imagine", hint: "ComfyUI · /imagine" },
          { id: "integrations", label: "Integrations", hint: "Google · Bandcamp" },
          { id: "platform", label: "Platform", hint: "DB · telemetry" },
        ],
      },
    ],

    get visibleGroups() {
      const q = (this.filter || "").toLowerCase().trim();
      if (!q) return this.sectionGroups;
      return this.sectionGroups
        .map((g) => ({
          ...g,
          items: g.items.filter(
            (it) => it.label.toLowerCase().includes(q) || it.hint.toLowerCase().includes(q) || it.id.includes(q),
          ),
        }))
        .filter((g) => g.items.length);
    },

    get validTabIds() {
      return this.sectionGroups.flatMap((g) => g.items.map((it) => it.id));
    },

    voiceFileName() {
      const p = this.s.voice?.ref_audio || "";
      const base = p.split(/[/\\]/).pop() || "";
      return base || this.currentVoice || "";
    },

    get voiceSelectValue() {
      return this._voiceFile || this.voiceFileName();
    },

    set voiceSelectValue(v) {
      if (!this._voiceUiReady || !v) return;
      this._voiceFile = v;
      const current = this.voiceFileName();
      if (v === current) return;
      this.selectVoiceFile(v);
    },

    setTab(id) {
      if (!this.validTabIds.includes(id)) return;
      this.tab = id;
      const url = new URL(window.location.href);
      url.searchParams.set("tab", id);
      history.replaceState(null, "", url);
    },

    initials() {
      const n = this.user.display_name || this.user.username || "?";
      return n.split(" ").map((p) => p[0]).join("").toUpperCase().slice(0, 2);
    },

    async saveIdentity() {
      this.savedId = false;
      this.errId = "";
      this.accountSaving = true;
      try {
        const res = await fetch(`/api/operators/${this.user.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            display_name: this.user.display_name,
            avatar_color: this.user.avatar_color,
          }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          this.errId = data.detail || "Save failed.";
          return;
        }
        this.savedId = true;
        setTimeout(() => { this.savedId = false; }, 2500);
      } catch (_) {
        this.errId = "Network error.";
      } finally {
        this.accountSaving = false;
      }
    },

    async changePassword() {
      this.savedPw = false;
      this.errPw = "";
      if (!this.newPw) {
        this.errPw = "Enter a new password.";
        return;
      }
      if (this.newPw.length < 8) {
        this.errPw = "Password must be at least 8 characters.";
        return;
      }
      if (this.newPw !== this.confirmPw) {
        this.errPw = "Passwords do not match.";
        return;
      }
      this.accountSaving = true;
      try {
        const res = await fetch(`/api/operators/${this.user.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ password: this.newPw }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          this.errPw = data.detail || "Failed to update password.";
          return;
        }
        this.savedPw = true;
        this.newPw = "";
        this.confirmPw = "";
        setTimeout(() => { this.savedPw = false; }, 2500);
      } catch (_) {
        this.errPw = "Network error.";
      } finally {
        this.accountSaving = false;
      }
    },

    clearPrefs() {
      localStorage.removeItem("maya.voice.settings.v1");
      if (this.user.username) {
        localStorage.removeItem(`maya_prefs_${this.user.username}`);
      }
      this.clearedPrefs = true;
      setTimeout(() => { this.clearedPrefs = false; }, 2000);
    },

    restoreConversationDetailed() {
      try {
        const stored = sessionStorage.getItem(_detailedStorageKey());
        this.conversationDetailed = stored === null ? true : stored === "1";
      } catch (_) {
        this.conversationDetailed = true;
      }
    },

    persistConversationDetailed() {
      try {
        sessionStorage.setItem(_detailedStorageKey(), this.conversationDetailed ? "1" : "0");
      } catch (_) {}
      const store = typeof Alpine !== "undefined" ? Alpine.store("mayaConversation") : null;
      if (store) store.detailed = this.conversationDetailed;
    },

    async refreshCatalog() {
      await this.refreshLlmModels();
      try {
        const r = await fetch("/api/voice/settings/catalog?llm=0");
        if (!r.ok) throw new Error("catalog failed");
        const data = await r.json();
        const llmModels = this.catalog.llm_models;
        this.catalog = { ...this.catalog, ...(data.catalog || {}), llm_models: llmModels };
        this.ensureCatalogDefaults();
      } catch (e) {
        this.error = String(e.message || e);
      }
    },


    isLitellmSdk() {
      const r = this.s.reasoning || {};
      if (r.provider !== "litellm") return false;
      return (r.litellm?.mode || "sdk") !== "proxy";
    },

    usesLmStudioCatalog() {
      const r = this.s.reasoning || {};
      if (r.provider === "webllm") return false;
      if (r.provider === "lm_studio") return true;
      return r.provider === "litellm" && (r.litellm?.mode || "sdk") === "proxy";
    },

    normalizeReasoning() {
      const r = this.s.reasoning;
      if (!r) return;
      if (!r.litellm) r.litellm = { mode: "sdk", model: "gemini/gemini-2.0-flash" };
      if (r.provider === "litellm") {
        const mode = r.litellm.mode || "sdk";
        const lm = (r.litellm.model || "").trim();
        if (mode === "sdk" && lm) r.model = lm;
      }
    },

    _llmCatalogUrl() {
      if (!this.usesLmStudioCatalog()) return "";
      const base = (this.s.reasoning?.base_url || "").trim();
      if (!base) return "";
      const params = new URLSearchParams({ llm: "1", base_url: base });
      const key = (this.s.reasoning?.api_key || "").trim();
      if (key) params.set("api_key", key);
      return `/api/voice/settings/catalog?${params}`;
    },

    async refreshLlmModels() {
      if (this.s.reasoning?.provider === "webllm") {
        this.llmModelsHint = "";
        return;
      }
      if (this.isLitellmSdk()) {
        const lm = this.s.reasoning?.litellm?.model || "";
        this.llmModelsHint = lm ? `LiteLLM SDK — ${lm}` : "Pick a LiteLLM model";
        this.llmModelsLoading = false;
        return;
      }
      const url = this._llmCatalogUrl();
      if (!url) {
        this.llmModelsHint = "Set a base URL to load models from LM Studio.";
        return;
      }
      this.llmModelsLoading = true;
      this.llmModelsHint = "";
      try {
        const r = await fetch(url);
        if (!r.ok) throw new Error(`Could not reach LLM server (HTTP ${r.status})`);
        const data = await r.json();
        const models = data.catalog?.llm_models || [];
        this.catalog.llm_models = models;
        if (!models.length) {
          this.llmModelsHint = "No models returned — open LM Studio and load a model.";
        } else {
          this.llmModelsHint = `${models.length} model${models.length === 1 ? "" : "s"} from server`;
          const current = this.s.reasoning?.model || "";
          if (current && !models.some((m) => m.id === current)) {
            this.s.reasoning.model = models[0].id;
            this.save();
          }
        }
      } catch (e) {
        this.llmModelsHint = String(e.message || e);
      } finally {
        this.llmModelsLoading = false;
      }
    },

    onReasoningUrlInput() {
      if (this._llmFetchTimer) clearTimeout(this._llmFetchTimer);
      this._llmFetchTimer = setTimeout(() => this.refreshLlmModels(), 600);
    },

    onApiKeyInput() {
      this.onReasoningUrlInput();
    },

    ensureCatalogDefaults() {
      const c = this.catalog;
      if (!c.whisper_models?.length) {
        c.whisper_models = ["tiny.en", "base.en", "small.en", "medium.en", "large-v3"];
      }
      if (!c.wispr_models?.length) {
        c.wispr_models = ["wispr-flow-1", "wispr-flow-1-fast", "wispr-flow-pro"];
      }
      if (!c.languages?.length) {
        c.languages = ["en", "es", "fr", "de", "ja", "pt"];
      }
      if (!c.tts_languages?.length) {
        c.tts_languages = ["English", "Chinese", "Japanese"];
      }
      if (!c.personas?.length) {
        c.personas = ["maya", "operator", "assistant", "technical"];
      }
      if (!c.eq_presets?.length) {
        c.eq_presets = [{ id: "off", label: "Off (bypass)" }];
      }
      this.ensureVoiceModelOptions();
    },

    ensureVoiceModelOptions() {
      const ensureModel = (list, id) => {
        const items = Array.isArray(list) ? [...list] : [];
        if (id && !items.some((m) => m.id === id)) {
          items.push({ id, label: id });
        }
        return items;
      };
      this.catalog.clone_models = ensureModel(
        this.catalog.clone_models,
        this.s.voice?.clone_model,
      );
      this.catalog.custom_tts_models = ensureModel(
        this.catalog.custom_tts_models,
        this.s.voice?.custom_model,
      );
      const speaker = this.s.voice?.speaker;
      if (speaker && !(this.catalog.speakers || []).includes(speaker)) {
        this.catalog.speakers = [...(this.catalog.speakers || []), speaker];
      }
      const lang = this.s.voice?.language;
      if (lang && !(this.catalog.tts_languages || []).includes(lang)) {
        this.catalog.tts_languages = [...(this.catalog.tts_languages || []), lang];
      }
    },

    syncVoiceCatalogSelection() {
      const voices = this.catalog.voices || [];
      const current = this.voiceFileName();
      if (!current) {
        this._voiceFile = "";
        return;
      }
      const base = current.split(/[/\\]/).pop() || current;
      const stem = base.replace(/\.[^.]+$/, "");
      let match = voices.find((v) => v.file === base || v.file === current);
      if (!match) {
        match = voices.find(
          (v) => v.file?.toLowerCase() === base.toLowerCase() || v.name === stem,
        );
      }
      if (match) {
        this._voiceFile = match.file;
        const path = match.file.includes("/") ? match.file : `voices/${match.file}`;
        if (this.s.voice.ref_audio !== path) {
          this.s.voice.ref_audio = path;
          this.s.voice.ref_text = "";
        }
      } else {
        this.catalog.voices = [...voices, { name: stem, file: base }];
        this._voiceFile = base;
      }
    },

    async init() {
      const tabParam = new URLSearchParams(window.location.search).get("tab");
      if (tabParam && this.validTabIds.includes(tabParam)) {
        this.tab = tabParam;
      }

      try {
        const [settingsR, accountR] = await Promise.all([
          fetch("/api/voice/settings"),
          fetch("/api/auth/me"),
        ]);
        if (accountR.ok) {
          const data = await accountR.json();
          if (!data.authenticated) {
            window.location.href = "/login?next=/settings";
            return;
          }
          this.user = {
            id: data.id,
            username: data.username,
            display_name: data.display_name,
            role: data.role,
            avatar_color: data.avatar_color || "#0a84ff",
          };
          window._mayaCurrentUser = { id: data.id, username: data.username };
          this.restoreConversationDetailed();
        }
        if (settingsR.ok) {
          const data = await settingsR.json();
          this.s = this.deepMerge(this.s, data.settings || {});
          this.normalizeWebLLM();
          this.normalizeReasoning();
          this.normalizeDiscordGuildId();
          this.ensureVoiceModelOptions();
        }
      } catch (e) {
        this.error = String(e.message || e);
      } finally {
        this.loading = false;
        this.$nextTick(() => {
          this.$root?.setAttribute?.("data-alpine-ready", "true");
        });
      }

      this.loadExtras();
      if (this.s.reasoning?.provider !== "webllm") {
        this.testConnection();
      } else {
        this.health = {
          status: "skipped",
          detail: "WebLLM runs in the browser — validate on the Conversation page.",
        };
      }
    },

    async loadExtras() {
      try {
        const [catalogR, statusR, cfgR] = await Promise.all([
          fetch("/api/voice/settings/catalog?llm=0"),
          fetch("/api/voice/agent/status"),
          fetch("/api/voice/agent/config"),
        ]);
        if (catalogR.ok) {
          const data = await catalogR.json();
          this.catalog = { ...this.catalog, ...(data.catalog || {}) };
          this.ensureCatalogDefaults();
        }
        if (statusR.ok) {
          const st = await statusR.json();
          this.agentReady = !!st.ready;
        }
        if (cfgR.ok) {
          const cfg = await cfgR.json();
          this.currentVoice = cfg.current_voice || cfg.voice || "";
          this.loadedTtsModel = cfg.loaded_tts_model || "";
          this.ensureVoiceModelOptions();
        }
        await this.loadVrmModels();
        await this.loadVrmBackgrounds();
        await this.loadAnimations();
        if (this.s.reasoning?.provider !== "webllm") {
          await this.refreshLlmModels();
        }
      } catch (e) {
        if (!this.error) this.error = String(e.message || e);
      } finally {
        this.syncVoiceCatalogSelection();
        this._voiceUiReady = true;
        this.$nextTick(() => {
          this.syncVoiceCatalogSelection();
        });
      }
    },

    deepMerge(base, patch) {
      const out = JSON.parse(JSON.stringify(base));
      for (const k of Object.keys(patch || {})) {
        if (patch[k] && typeof patch[k] === "object" && !Array.isArray(patch[k])) {
          out[k] = this.deepMerge(out[k] || {}, patch[k]);
        } else {
          out[k] = patch[k];
        }
      }
      return out;
    },

    normalizeWebLLM() {
      if (this.s.reasoning?.provider === "webllm") {
        if (!this.s.reasoning.webllm) this.s.reasoning.webllm = {};
        this.s.reasoning.webllm.enabled = true;
      } else if (this.s.reasoning?.webllm) {
        this.s.reasoning.webllm.enabled = false;
      }
    },

    onLitellmChange() {
      this.s.reasoning.provider = "litellm";
      this.normalizeReasoning();
      this.save();
      if (this.isLitellmSdk()) {
        this.llmModelsHint = this.s.reasoning?.litellm?.model
          ? `LiteLLM SDK — ${this.s.reasoning.litellm.model}`
          : "Pick a LiteLLM model";
      } else {
        this.refreshLlmModels();
      }
      this.testConnection();
    },

    async onProviderChange() {
      const leavingWebLLM = this.s.reasoning?.provider !== "webllm";
      this.normalizeWebLLM();
      if (this.s.reasoning?.provider === "litellm") this.normalizeReasoning();
      if (leavingWebLLM && window.mayaWebLLMBridge?.unload) {
        await window.mayaWebLLMBridge.unload();
      }
      this.save();
      if (this.s.reasoning?.provider === "webllm") {
        this.health = {
          status: "skipped",
          detail: "WebLLM runs in the browser — validate on the Conversation page.",
        };
        this.warn = this.health.detail;
        this.error = "";
      } else {
        await this.refreshLlmModels();
        this.testConnection();
      }
    },

    async testConnection() {
      if (this.s.reasoning?.provider === "webllm") {
        this.health = {
          status: "skipped",
          detail: "WebLLM runs in the browser — validate on the Conversation page.",
        };
        this.warn = this.health.detail;
        return;
      }
      this.healthTesting = true;
      this.warn = "";
      this.error = "";
      try {
        const r = await fetch("/api/voice/settings/health", { method: "POST" });
        if (!r.ok) throw new Error("Health check failed");
        const data = await r.json();
        this.health = data.health || null;
        if (this.health?.status) {
          this.health.status = String(this.health.status).toLowerCase();
        }
        if (this.health?.status === "error") {
          this.error = this.health.detail || "LLM connection error";
        } else if (this.health?.status === "warn" || this.health?.status === "skipped") {
          this.warn = this.health.detail || "LLM connection degraded";
        }
      } catch (e) {
        this.error = String(e.message || e);
        this.health = { status: "error", detail: String(e.message || e) };
      } finally {
        this.healthTesting = false;
      }
    },

    async testImagineConnection() {
      this.imagineHealthTesting = true;
      try {
        const r = await fetch("/api/voice/settings/imagine-health", { method: "POST" });
        if (!r.ok) throw new Error("ComfyUI health check failed");
        const data = await r.json();
        this.imagineHealth = data.health || null;
      } catch (e) {
        this.imagineHealth = { status: "error", detail: String(e.message || e) };
      } finally {
        this.imagineHealthTesting = false;
      }
    },

    imagineWeightsSummary() {
      const weights = this.imagineHealth?.weights;
      if (!weights) return "";
      const parts = [];
      for (const key of ["zit", "krea2"]) {
        const probe = weights[key];
        if (!probe || typeof probe !== "object") continue;
        const label = key === "krea2" ? "Krea2" : "Z-Image";
        if (probe.ok) {
          parts.push(`${label}: ok`);
        } else if (key === "krea2" && probe.capability && probe.capability.ok === false) {
          const ver = probe.capability.comfyui_version || "unknown";
          parts.push(`${label}: needs ComfyUI 0.27+ (have ${ver})`);
        } else {
          const missing = Array.isArray(probe.missing) ? probe.missing.join(", ") : "missing";
          parts.push(`${label}: ${missing || "missing"}`);
        }
      }
      return parts.join(" · ");
    },

    get remarkVisionSelect() {
      const value = String(this.s.imagine?.remark_vision_model || "").trim();
      if (!value) return "";
      const ids = (this.catalog.remark_vision_models || []).map((m) => m.id);
      return ids.includes(value) ? value : "__custom__";
    },

    get remarkVisionCustom() {
      return this.remarkVisionSelect === "__custom__";
    },

    onRemarkVisionSelectChange(value) {
      if (value === "__custom__") return;
      this.s.imagine.remark_vision_model = value;
      this.save();
    },

    normalizeDiscordGuildId() {
      const disc = this.s?.discord;
      if (!disc) return;
      const gid = disc.guild_id;
      if (gid == null || gid === "" || gid === 0) {
        disc.guild_id = "";
        return;
      }
      disc.guild_id = String(gid);
    },

    activeTtsModelId() {
      const mode = (this.s.delivery?.tts_mode || "clone").toLowerCase();
      return mode === "clone"
        ? (this.s.voice?.clone_model || "")
        : (this.s.voice?.custom_model || "");
    },

    async onTtsEngineChange() {
      this.ttsReloading = true;
      this.ttsStatus = "Switching TTS model…";
      this.error = "";
      try {
        await this._saveNow();
        await this.waitForTtsReload();
      } catch (e) {
        this.error = String(e.message || e);
      } finally {
        this.ttsReloading = false;
      }
    },

    async waitForTtsReload(maxMs = 180000) {
      const want = this.activeTtsModelId();
      const deadline = Date.now() + maxMs;
      while (Date.now() < deadline) {
        const [statusR, cfgR] = await Promise.all([
          fetch("/api/voice/agent/status"),
          fetch("/api/voice/agent/config"),
        ]);
        if (statusR.ok && cfgR.ok) {
          const st = await statusR.json();
          const cfg = await cfgR.json();
          if (st.ready) {
            this.agentReady = true;
            this.loadedTtsModel = cfg.loaded_tts_model || "";
            if (!want || this.loadedTtsModel === want) {
              const label = (this.loadedTtsModel || want).split("/").pop();
              this.ttsStatus = label ? `Loaded: ${label}` : "";
              setTimeout(() => { this.ttsStatus = ""; }, 5000);
              return;
            }
          }
        }
        await new Promise((r) => setTimeout(r, 1200));
      }
      this.ttsStatus = "TTS reload is still running — check server console for progress.";
    },

    save() {
      if (this._saveTimer) clearTimeout(this._saveTimer);
      this._saveTimer = setTimeout(() => this._saveNow(), 400);
    },

    async _saveNow() {
      this._saveTimer = null;
      this.saved = false;
      this.error = "";
      this.normalizeReasoning();
      this.normalizeDiscordGuildId();
      try {
        const r = await fetch("/api/voice/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ settings: this.s }),
        });
        if (!r.ok) throw new Error("Save failed");
        const data = await r.json();
        if (data.settings) {
          const typedKey = (this.s.reasoning?.api_key || "").trim();
          const hadTypedKey = typedKey && typedKey !== "lm-studio" && typedKey !== "local-model";
          this.s = this.deepMerge(this.s, data.settings);
          this.normalizeReasoning();
          if (hadTypedKey && this.s.reasoning) {
            this.s.reasoning.api_key_configured = true;
            this.s.reasoning.api_key = "lm-studio";
          }
        }
        this.saved = true;
        setTimeout(() => { this.saved = false; }, 2500);
      } catch (e) {
        this.error = String(e.message || e);
      }
    },

    async selectVoiceFile(file) {
      if (!file) return;
      this.s.voice.ref_audio = file.includes("/") ? file : `voices/${file}`;
      this.s.voice.ref_text = "";
      await this._saveNow();
      const base = file.split(/[/\\]/).pop();
      this.currentVoice = base.replace(/\.[^.]+$/, "");
      if (!this.agentReady) return;
      try {
        const r = await fetch("/api/voice/agent/select-voice", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ file: base }),
        });
        const data = await r.json();
        if (!data.ok) {
          this.error = data.error || "Voice switch failed";
        }
      } catch (e) {
        this.error = String(e.message || e);
      }
    },

    async uploadVoice(ev) {
      const file = ev.target?.files?.[0];
      if (!file) return;
      if (this.voiceUploadBusy) return;
      const fd = new FormData();
      fd.append("file", file);
      const label = (this.voiceUploadName || "").trim();
      if (label) fd.append("name", label);
      this.error = "";
      this.voiceUploadBusy = true;
      try {
        const r = await fetch("/api/voice/agent/upload-voice", {
          method: "POST",
          body: fd,
          credentials: "same-origin",
        });
        let data = {};
        try {
          data = await r.json();
        } catch (_) {
          this.error = `Upload failed (HTTP ${r.status})`;
          return;
        }
        if (!r.ok || !data.ok) {
          this.error = data.error || data.detail || `Upload failed (HTTP ${r.status})`;
          return;
        }
        this.catalog.voices = data.voices || this.catalog.voices;
        const uploaded = data.file || data.name;
        if (uploaded) {
          const fname = String(uploaded).includes(".") ? uploaded : `${uploaded}.wav`;
          this.s.voice.ref_audio = fname.includes("/") ? fname : `voices/${fname}`;
          this.s.voice.ref_text = "";
          this.syncVoiceCatalogSelection();
          await this._saveNow();
          this.currentVoice = data.name || fname.replace(/\.[^.]+$/, "");
          if (this.agentReady) {
            try {
              const sel = await fetch("/api/voice/agent/select-voice", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "same-origin",
                body: JSON.stringify({ file: fname.split(/[/\\]/).pop() }),
              });
              const selData = await sel.json();
              if (!selData.ok) {
                this.error = selData.error || "Voice saved but activation failed — pick it from the list.";
              }
            } catch (_) {
              this.error = "Voice saved — pick it from Reference clip when the agent is ready.";
            }
          }
        }
        this.saved = true;
        setTimeout(() => { this.saved = false; }, 2500);
        this.voiceUploadName = "";
      } catch (e) {
        this.error = String(e.message || e);
      } finally {
        this.voiceUploadBusy = false;
        ev.target.value = "";
      }
    },

    async loadVrmModels() {
      try {
        const r = await fetch("/api/voice/agent/vrm/models");
        if (!r.ok) return;
        const data = await r.json();
        this.catalog.vrm_models = data.models || [];
      } catch (_) {}
    },

    async loadVrmBackgrounds() {
      try {
        const r = await fetch("/api/voice/agent/vrm/backgrounds");
        if (!r.ok) return;
        const data = await r.json();
        this.catalog.vrm_backgrounds = data.backgrounds || [];
      } catch (_) {}
    },

    async loadAnimations() {
      try {
        const r = await fetch("/api/voice/agent/animations");
        if (!r.ok) return;
        const data = await r.json();
        this.catalog.animations = (data.catalog || []).map((c) => c.file || c).length
          ? (data.catalog || []).map((c) => (typeof c === "string" ? c : c.file))
          : (data.animations || []);
      } catch (_) {}
    },

    async uploadVrm(ev) {
      const file = ev.target?.files?.[0];
      if (!file) return;
      const fd = new FormData();
      fd.append("file", file);
      const label = (this.vrmUploadName || "").trim();
      if (label) fd.append("name", label);
      this.error = "";
      try {
        const r = await fetch("/api/voice/agent/upload-vrm", {
          method: "POST",
          body: fd,
          credentials: "same-origin",
        });
        const data = await r.json();
        if (!data.ok) {
          this.error = data.error || "VRM upload failed";
          return;
        }
        this.catalog.vrm_models = data.models || this.catalog.vrm_models;
        if (data.file) {
          this.s.vrm.model = data.file;
          await this._saveNow();
        }
        this.vrmUploadName = "";
      } catch (e) {
        this.error = String(e.message || e);
      }
      ev.target.value = "";
    },

    async uploadVrmBackground(ev) {
      const file = ev.target?.files?.[0];
      if (!file) return;
      const fd = new FormData();
      fd.append("file", file);
      const label = (this.vrmBgUploadName || "").trim();
      if (label) fd.append("name", label);
      this.error = "";
      try {
        const r = await fetch("/api/voice/agent/upload-vrm-background", {
          method: "POST",
          body: fd,
          credentials: "same-origin",
        });
        const data = await r.json();
        if (!data.ok) {
          this.error = data.error || "Background upload failed";
          return;
        }
        this.catalog.vrm_backgrounds = data.backgrounds || this.catalog.vrm_backgrounds;
        if (data.file) {
          this.s.vrm.background_preset = "custom";
          this.s.vrm.background_image = data.file;
          await this._saveNow();
        }
        this.vrmBgUploadName = "";
      } catch (e) {
        this.error = String(e.message || e);
      }
      ev.target.value = "";
    },
  }));
});
