/**
 * Maya Voice SDK — a drop-in "kitchen-sink" set of Alpine.js components for
 * the operator voice control panel and the conversational pipeline:
 *
 *     listen (detection engine) -> reasoning model -> Maya's conversational turn
 *
 * Convergence: this SDK is built on Alpine.js (same pattern as
 * static/gateway/imagine-*.js) so it drops into any server-rendered surface
 * with a single <script> — no build step.
 *
 * Usage on any page:
 *   <link rel="stylesheet" href="/sdk/maya-voice-sdk.css">
 *   <script defer src="/sdk/maya-voice-sdk.js"></script>
 *   <script defer src="/sdk/vendor/alpine.min.js"></script>   (load Alpine LAST)
 *
 * Then attach any component, e.g.:
 *   <div x-data="mayaVocalInput()"> ... </div>
 *   <div x-data="mayaDetectionEngine()"> ... </div>
 *   <div x-data="mayaSettingsPanel()"> ... </div>
 *   <div x-data="mayaPipeline()"> ... </div>
 *
 * All components share a single Alpine.store("mayaVoice"), so they compose:
 * changing a device or VAD threshold in one panel is reflected everywhere.
 */
(function () {
  "use strict";

  var SETTINGS_KEY = "maya.voice.settings.v1";
  var API_BASE = (window.MAYA_VOICE_API_BASE || "").replace(/\/$/, "");

  function clamp(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v));
  }

  function loadStoredSettings() {
    try {
      var raw = window.localStorage.getItem(SETTINGS_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (_) {
      return null;
    }
  }

  document.addEventListener("alpine:init", function () {
    Alpine.store("mayaVoice", {
      ready: false,
      catalog: {
        detection_modes: ["vad", "push_to_talk", "continuous"],
        wispr_models: [],
        reasoning_models: [],
        languages: [],
      },
      settings: {
        input_device_id: null,
        output_device_id: null,
        input_gain: 1.0,
        noise_suppression: true,
        detection_mode: "vad",
        vad_threshold: 0.02,
        vad_hangover_ms: 600,
        push_to_talk_key: "Space",
        wispr_model: "wispr-flow-1",
        language: "en",
        auto_punctuation: true,
        filler_removal: true,
        reasoning_model: "maya-reason-mini",
        persona: "maya",
      },
      devices: { inputs: [], outputs: [] },

      // live audio/detection state
      // bars: geometric frequency spectrum (0..1), driven mathematically.
      audio: {
        running: false,
        source: null,
        level: 0,
        peak: 0,
        speaking: false,
        bars: new Array(28).fill(0),
      },

      // pipeline state
      transcript: "",
      status: "idle", // idle | listening | thinking
      turns: [], // [{role, text, intent?, trace?, latency?}]
      lastTrace: [],

      // --- private audio plumbing (not reactive) ---
      _ctx: null,
      _analyser: null,
      _stream: null,
      _sim: null,
      _raf: null,
      _lastAboveTs: 0,
      _simPhase: 0,

      async loadDefaults() {
        try {
          var resp = await fetch(API_BASE + "/api/voice/settings/defaults");
          if (resp.ok) {
            var data = await resp.json();
            this.catalog = {
              detection_modes: data.detection_modes,
              wispr_models: data.wispr_models,
              reasoning_models: data.reasoning_models,
              languages: data.languages,
            };
            this.settings = Object.assign({}, data.default_settings);
          }
        } catch (_) {
          /* offline: keep built-in defaults */
        }
        var stored = loadStoredSettings();
        if (stored) this.settings = Object.assign({}, this.settings, stored);
        this.ready = true;
      },

      persist() {
        try {
          window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(this.settings));
        } catch (_) {
          /* ignore */
        }
      },

      async enumerateDevices() {
        if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
          return;
        }
        try {
          var list = await navigator.mediaDevices.enumerateDevices();
          this.devices.inputs = list
            .filter(function (d) { return d.kind === "audioinput"; })
            .map(function (d, i) {
              return { id: d.deviceId, label: d.label || "Microphone " + (i + 1) };
            });
          this.devices.outputs = list
            .filter(function (d) { return d.kind === "audiooutput"; })
            .map(function (d, i) {
              return { id: d.deviceId, label: d.label || "Speaker " + (i + 1) };
            });
        } catch (_) {
          /* permission denied or unsupported */
        }
      },

      _ensureCtx() {
        if (!this._ctx) {
          var AC = window.AudioContext || window.webkitAudioContext;
          this._ctx = new AC();
        }
        if (this._ctx.state === "suspended") this._ctx.resume();
        if (!this._analyser) {
          this._analyser = this._ctx.createAnalyser();
          this._analyser.fftSize = 1024;
        }
        return this._ctx;
      },

      async startMic() {
        this._ensureCtx();
        var constraints = {
          audio: {
            noiseSuppression: !!this.settings.noise_suppression,
            echoCancellation: true,
          },
        };
        if (this.settings.input_device_id) {
          constraints.audio.deviceId = { exact: this.settings.input_device_id };
        }
        this._stream = await navigator.mediaDevices.getUserMedia(constraints);
        var src = this._ctx.createMediaStreamSource(this._stream);
        src.connect(this._analyser);
        this.audio.source = "mic";
        await this.enumerateDevices();
        this._begin();
      },

      // Simulated source: a silent oscillator whose gain envelope is modulated
      // to mimic speech bursts. Real Web Audio RMS is read from the analyser,
      // so the meter + detection engine are genuinely exercised without a mic.
      startSimulated() {
        var ctx = this._ensureCtx();
        var osc = ctx.createOscillator();
        osc.type = "sawtooth";
        osc.frequency.value = 165;
        var gain = ctx.createGain();
        gain.gain.value = 0.0001;
        osc.connect(gain);
        gain.connect(this._analyser);
        osc.start();
        this._sim = { osc: osc, gain: gain };
        this.audio.source = "simulated";
        this._begin();
      },

      _begin() {
        this.audio.running = true;
        this.audio.peak = 0;
        this._lastAboveTs = 0;
        var self = this;
        var buf = new Uint8Array(this._analyser.fftSize);
        var freq = new Uint8Array(this._analyser.frequencyBinCount);
        var nBars = this.audio.bars.length;

        function frame(ts) {
          if (!self.audio.running) return;

          if (self._sim) {
            // speech-burst envelope: ~900ms speaking, ~600ms pause
            self._simPhase = (self._simPhase + 16) % 1500;
            var speaking = self._simPhase < 900;
            var env = speaking
              ? 0.25 + 0.2 * Math.abs(Math.sin(self._simPhase / 90))
              : 0.0001;
            self._sim.gain.gain.value = env;
          }

          self._analyser.getByteTimeDomainData(buf);
          var sum = 0;
          for (var i = 0; i < buf.length; i++) {
            var v = (buf[i] - 128) / 128;
            sum += v * v;
          }
          var rms = Math.sqrt(sum / buf.length);
          var level = clamp(rms * (self.settings.input_gain || 1) * 1.8, 0, 1);
          self.audio.level = level;
          if (level > self.audio.peak) self.audio.peak = level;

          // Geometric spectrum: average FFT bins into nBars, log-ish spread.
          self._analyser.getByteFrequencyData(freq);
          var usable = Math.floor(freq.length * 0.62); // drop empty high end
          var bars = self.audio.bars;
          for (var b = 0; b < nBars; b++) {
            var lo = Math.floor((b / nBars) * usable);
            var hi = Math.max(lo + 1, Math.floor(((b + 1) / nBars) * usable));
            var acc = 0;
            for (var k = lo; k < hi; k++) acc += freq[k];
            var val = clamp((acc / (hi - lo) / 255) * (self.settings.input_gain || 1), 0, 1);
            // light smoothing for a stable, non-jittery readout
            bars[b] = bars[b] * 0.6 + val * 0.4;
          }

          // --- detection engine (VAD with hangover) ---
          var now = ts || performance.now();
          var mode = self.settings.detection_mode;
          var isSpeech;
          if (mode === "continuous") {
            isSpeech = true;
          } else if (mode === "push_to_talk") {
            isSpeech = self._pttDown === true;
          } else {
            if (level >= self.settings.vad_threshold) self._lastAboveTs = now;
            isSpeech = now - self._lastAboveTs < (self.settings.vad_hangover_ms || 600);
          }
          if (isSpeech !== self.audio.speaking) {
            self.audio.speaking = isSpeech;
            window.dispatchEvent(
              new CustomEvent(isSpeech ? "maya:speechstart" : "maya:speechend")
            );
          }

          self._raf = requestAnimationFrame(frame);
        }
        this._raf = requestAnimationFrame(frame);
        this.status = "listening";
      },

      stop() {
        this.audio.running = false;
        this.audio.speaking = false;
        this.audio.level = 0;
        this.audio.bars = this.audio.bars.map(function () { return 0; });
        if (this._raf) cancelAnimationFrame(this._raf);
        this._raf = null;
        if (this._stream) {
          this._stream.getTracks().forEach(function (t) { t.stop(); });
          this._stream = null;
        }
        if (this._sim) {
          try { this._sim.osc.stop(); } catch (_) {}
          this._sim = null;
        }
        this.audio.source = null;
        if (this.status === "listening") this.status = "idle";
      },

      async sendTurn(text) {
        var transcript = (text != null ? text : this.transcript).trim();
        if (!transcript || this.status === "thinking") return null;
        this.status = "thinking";
        this.turns.push({ role: "operator", text: transcript });
        var history = this.turns
          .slice(0, -1)
          .map(function (t) { return { role: t.role, text: t.text }; });
        try {
          var resp = await fetch(API_BASE + "/api/voice/turn", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              transcript: transcript,
              settings: this.settings,
              history: history,
            }),
          });
          if (!resp.ok) throw new Error("turn failed: " + resp.status);
          var data = await resp.json();
          this.turns.push({
            role: "maya",
            text: data.maya_turn,
            intent: data.intent,
            trace: data.reasoning_trace,
            latency: data.latency_ms,
          });
          this.lastTrace = data.reasoning_trace || [];
          this.transcript = "";
          return data;
        } catch (err) {
          this.turns.push({ role: "maya", text: "(pipeline error: " + err.message + ")" });
          return null;
        } finally {
          this.status = this.audio.running ? "listening" : "idle";
        }
      },

      reset() {
        this.turns = [];
        this.lastTrace = [];
        this.transcript = "";
      },
    });
  });

  // ---------- Component factories (attach with x-data="...") ----------

  window.mayaSettingsPanel = function () {
    return {
      get s() { return this.$store.mayaVoice.settings; },
      get cat() { return this.$store.mayaVoice.catalog; },
      init() {
        var store = this.$store.mayaVoice;
        if (!store.ready) store.loadDefaults();
      },
      save() { this.$store.mayaVoice.persist(); },
    };
  };

  window.mayaDevicePanel = function () {
    return {
      get v() { return this.$store.mayaVoice; },
      async init() {
        var store = this.$store.mayaVoice;
        if (!store.ready) await store.loadDefaults();
        await store.enumerateDevices();
      },
      async refresh() { await this.$store.mayaVoice.enumerateDevices(); },
      onChange() { this.$store.mayaVoice.persist(); },
    };
  };

  window.mayaVocalInput = function () {
    return {
      error: "",
      get v() { return this.$store.mayaVoice; },
      get levelPct() { return Math.round(this.$store.mayaVoice.audio.level * 100); },
      get peakPct() { return Math.round(this.$store.mayaVoice.audio.peak * 100); },
      async startMic() {
        this.error = "";
        try {
          await this.$store.mayaVoice.startMic();
        } catch (e) {
          this.error = "Mic unavailable (" + (e.name || e.message) + "). Use Simulate input.";
        }
      },
      simulate() {
        this.error = "";
        this.$store.mayaVoice.startSimulated();
      },
      stop() { this.$store.mayaVoice.stop(); },
    };
  };

  window.mayaDetectionEngine = function () {
    return {
      get v() { return this.$store.mayaVoice; },
      get s() { return this.$store.mayaVoice.settings; },
      get thresholdPct() { return Math.round(this.$store.mayaVoice.settings.vad_threshold * 100); },
      save() { this.$store.mayaVoice.persist(); },
    };
  };

  window.mayaPipeline = function () {
    return {
      get v() { return this.$store.mayaVoice; },
      init() {
        var store = this.$store.mayaVoice;
        if (!store.ready) store.loadDefaults();
      },
      send() { this.$store.mayaVoice.sendTurn(); },
      onKeydown(e) {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          this.send();
        }
      },
      reset() { this.$store.mayaVoice.reset(); },
    };
  };
})();
