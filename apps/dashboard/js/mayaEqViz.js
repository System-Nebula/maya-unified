/** Live output EQ — EqVisualizer themed for Maya Unified. */
document.addEventListener("alpine:init", () => {
  Alpine.data("mayaEqViz", () => ({
    eqEnabled: true,
    eqPreset: "off",
    eqPresets: [],
    speaking: false,
    selectedBand: null,
    bandType: "peak",
    bandFreq: 1000,
    bandGain: 0,
    bandQ: 0.707,
    _viz: null,
    _specTimer: null,
    _unsub: null,

    get agentReady() {
      return Alpine.store("mayaShell")?.ready || false;
    },

    get presetLabel() {
      const p = this.eqPresets.find((x) => x.id === this.eqPreset);
      return p?.label || this.eqPreset || "Off";
    },

    async init() {
      await this.$nextTick();
      const canvas = this.$refs.eqCanvas;
      if (!canvas || typeof EqVisualizer === "undefined") return;

      this._viz = new EqVisualizer(canvas, {
        onChange: (payload) => this.postEqConfig({ eq_preset: "custom", eq_bands: payload.bands }),
        onSelect: (idx, band) => this.syncBandPanel(idx, band),
      });

      this._unsub = window.mayaAgentEvents?.subscribe((ev) => this.onAgentEvent(ev));
      await this.loadConfig();
      this.$nextTick(() => this._viz?.resize());
      window.addEventListener("resize", () => {
        if (this._viz) setTimeout(() => this._viz.resize(), 50);
      });
    },

    destroy() {
      this.stopSpectrumPoll();
      if (this._unsub) this._unsub();
    },

    onAgentEvent(ev) {
      if (ev.type === "status") {
        const v = ev.value || "idle";
        if (v === "speaking") {
          this.speaking = true;
          this._viz?.setSpeaking(true);
          this.$nextTick(() => this._viz?.resize());
          this.startSpectrumPoll();
        } else if (this.speaking && v !== "speaking") {
          this.speaking = false;
          this._viz?.setSpeaking(false);
          this.stopSpectrumPoll();
        }
      }
      if (ev.type === "settings") {
        if (typeof ev.eq_enabled === "boolean") {
          this.eqEnabled = ev.eq_enabled;
          this._viz?.setEnabled(ev.eq_enabled);
        }
        if (ev.eq_preset || ev.eq_bands) {
          this.applyEqFromEvent(ev);
        }
      }
      if (ev.type === "ready" && ev.value) {
        this.loadConfig();
        this.$nextTick(() => this._viz?.resize());
      }
    },

    async loadConfig() {
      try {
        const r = await fetch("/api/voice/agent/config");
        if (!r.ok) return;
        const d = await r.json();
        if (Array.isArray(d.eq_presets)) {
          this.eqPresets = d.eq_presets;
          if (!this.eqPresets.some((p) => p.id === this.eqPreset)) {
            this.eqPreset = d.eq_preset || "off";
          }
        }
        if (d.eq_catalog && this._viz) this._viz.setCatalog(d.eq_catalog);
        this.eqEnabled = d.eq_enabled !== false;
        if (this._viz) {
          this._viz.setEnabled(this.eqEnabled);
          this._viz.setPreset(d.eq_preset || "off", d.eq_bands);
          this._viz.resize();
        }
        this.eqPreset = d.eq_preset || "off";
      } catch (_) {}
    },

    applyEqFromEvent(ev) {
      if (ev.eq_preset) this.eqPreset = ev.eq_preset;
      if (this._viz) {
        if (typeof ev.eq_enabled === "boolean") this._viz.setEnabled(ev.eq_enabled);
        this._viz.setPreset(ev.eq_preset || this.eqPreset, ev.eq_bands);
      }
    },

    onPresetChange() {
      if (!this._viz) return;
      this.deselectBand();
      this._viz.setPreset(this.eqPreset);
      this.postEqConfig({ eq_preset: this.eqPreset });
    },

    onEqToggle() {
      this._viz?.setEnabled(this.eqEnabled);
      this.postEqConfig({ eq_enabled: this.eqEnabled });
    },

    syncBandPanel(idx, band) {
      if (!band || idx < 0) {
        this.selectedBand = null;
        return;
      }
      this.selectedBand = idx + 1;
      this.bandType = band.type || "peak";
      this.bandFreq = Math.round(band.freq);
      this.bandGain = Number(band.gain_db || 0);
      this.bandQ = Number(band.q || 0.707);
    },

    deselectBand() {
      this.selectedBand = null;
      this._viz?.deselect?.();
    },

    onBandTypeChange() {
      if (!this._viz) return;
      this._viz.updateBandParam("type", this.bandType);
    },

    onBandFreqChange() {
      if (!this._viz) return;
      this._viz.updateBandParam("freq", parseFloat(this.bandFreq));
    },

    onBandGainChange() {
      if (!this._viz) return;
      this._viz.updateBandParam("gain_db", parseFloat(this.bandGain));
    },

    onBandQChange() {
      if (!this._viz) return;
      this._viz.updateBandParam("q", parseFloat(this.bandQ));
    },

    formatFreq(hz) {
      const n = Number(hz);
      if (!n || n < 0) return "—";
      if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)} kHz`;
      return `${Math.round(n)} Hz`;
    },

    async postEqConfig(payload) {
      try {
        await fetch("/api/voice/agent/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      } catch (_) {}
    },

    startSpectrumPoll() {
      if (this._specTimer) return;
      this._specTimer = setInterval(async () => {
        try {
          const r = await fetch("/api/voice/agent/spectrum");
          const d = await r.json();
          this._viz?.setSpectrumFrame(Array.isArray(d.bands) ? d.bands : []);
        } catch (_) {}
      }, 60);
    },

    stopSpectrumPoll() {
      if (this._specTimer) {
        clearInterval(this._specTimer);
        this._specTimer = null;
      }
      this._viz?.setSpectrumFrame([]);
    },
  }));
});
