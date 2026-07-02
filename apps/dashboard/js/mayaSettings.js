/** Comprehensive settings UI — GET/POST /api/voice/settings + operator account */
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
    loading: true,
    agentReady: false,
    currentVoice: "",
    _saveTimer: null,

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

    catalog: {
      eq_presets: [],
      voices: [],
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
      webllm_models: [],
      clone_models: [],
      custom_tts_models: [],
      tts_languages: [],
      personas: ["maya", "operator", "assistant", "technical"],
    },
    s: {
      audio: { output_volume: 1, eq_enabled: true, eq_preset: "off", aec_enabled: true },
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
      discord: {
        enabled: false, token: "", guild_id: 0, auto_reply: true,
        music_volume: 0.85, imagine_enabled: false, comfyui_url: "http://localhost:3000",
        default_voice_channel: "", youtube_cookies_browser: "", youtube_cookies_file: "",
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
          { id: "expressions", label: "Expressions", hint: "VTube Studio" },
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

    async refreshCatalog() {
      try {
        const r = await fetch("/api/voice/settings/catalog");
        if (!r.ok) throw new Error("catalog failed");
        const data = await r.json();
        this.catalog = { ...this.catalog, ...(data.catalog || {}) };
        this.ensureCatalogDefaults();
      } catch (e) {
        this.error = String(e.message || e);
      }
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
    },

    async init() {
      const tabParam = new URLSearchParams(window.location.search).get("tab");
      if (tabParam && this.validTabIds.includes(tabParam)) {
        this.tab = tabParam;
      }

      try {
        const [settingsR, catalogR, statusR, accountR] = await Promise.all([
          fetch("/api/voice/settings"),
          fetch("/api/voice/settings/catalog"),
          fetch("/api/voice/agent/status"),
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
        }
        if (settingsR.ok) {
          const data = await settingsR.json();
          this.s = this.deepMerge(this.s, data.settings || {});
        }
        if (catalogR.ok) {
          const data = await catalogR.json();
          this.catalog = { ...this.catalog, ...(data.catalog || {}) };
        }
        this.ensureCatalogDefaults();
        if (statusR.ok) {
          const st = await statusR.json();
          this.agentReady = !!st.ready;
        }
        const cfgR = await fetch("/api/voice/agent/config");
        if (cfgR.ok) {
          const cfg = await cfgR.json();
          this.currentVoice = cfg.current_voice || cfg.voice || "";
        }
      } catch (e) {
        this.error = String(e.message || e);
      } finally {
        this.loading = false;
        this.$nextTick(() => {
          this.$root?.setAttribute?.("data-alpine-ready", "true");
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

    save() {
      if (this._saveTimer) clearTimeout(this._saveTimer);
      this._saveTimer = setTimeout(() => this._saveNow(), 400);
    },

    async _saveNow() {
      this._saveTimer = null;
      this.saved = false;
      this.error = "";
      try {
        const r = await fetch("/api/voice/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ settings: this.s }),
        });
        if (!r.ok) throw new Error("Save failed");
        this.saved = true;
        setTimeout(() => { this.saved = false; }, 2500);
      } catch (e) {
        this.error = String(e.message || e);
      }
    },

    async selectVoiceFile(file) {
      if (!file) return;
      this.s.voice.ref_audio = file.includes("/") ? file : `voices/${file}`;
      await this._saveNow();
      if (!this.agentReady) return;
      try {
        const base = file.split(/[/\\]/).pop();
        const r = await fetch("/api/voice/agent/select-voice", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ file: base }),
        });
        const data = await r.json();
        if (!data.ok) this.error = data.error || "Voice switch failed";
        else this.currentVoice = base.replace(/\.[^.]+$/, "");
      } catch (e) {
        this.error = String(e.message || e);
      }
    },

    async uploadVoice(ev) {
      const file = ev.target?.files?.[0];
      if (!file) return;
      const fd = new FormData();
      fd.append("file", file);
      try {
        const r = await fetch("/api/voice/agent/upload-voice", { method: "POST", body: fd });
        const data = await r.json();
        if (!data.ok) {
          this.error = data.error || "Upload failed";
          return;
        }
        const catR = await fetch("/api/voice/settings/catalog");
        if (catR.ok) {
          const c = await catR.json();
          this.catalog.voices = c.catalog?.voices || this.catalog.voices;
        }
        if (data.file) await this.selectVoiceFile(data.file);
      } catch (e) {
        this.error = String(e.message || e);
      }
      ev.target.value = "";
    },
  }));
});
