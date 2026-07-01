/**
 * FabFilter Pro-Q inspired live EQ visualizer.
 * Renders frequency response curves, draggable band nodes, and a spectrum overlay.
 */
(function (global) {
  "use strict";

  const SR = 48000;
  const FMIN = 20;
  const FMAX = 20000;
  const GMIN = -12;
  const GMAX = 12;
  const COLORS = ["#0a84ff", "#409cff", "#64b5ff", "#5ac8fa", "#0077ed", "#2997ff", "#7ec8ff"];

  function logFreq(f) {
    return (Math.log10(f) - Math.log10(FMIN)) / (Math.log10(FMAX) - Math.log10(FMIN));
  }
  function invLogFreq(t) {
    return FMIN * Math.pow(FMAX / FMIN, t);
  }

  function makeCoeffs(spec) {
    const ftype = spec.type;
    const freq = Math.max(20, Math.min(spec.freq, SR * 0.49));
    const q = Math.max(0.1, spec.q || 0.707);
    const gainDb = spec.gain_db || 0;
    const w0 = (2 * Math.PI * freq) / SR;
    const cosw0 = Math.cos(w0);
    const sinw0 = Math.sin(w0);
    const alpha = sinw0 / (2 * q);
    let b0, b1, b2, a0, a1, a2;

    if (ftype === "lowpass") {
      b0 = (1 - cosw0) / 2; b1 = 1 - cosw0; b2 = (1 - cosw0) / 2;
      a0 = 1 + alpha; a1 = -2 * cosw0; a2 = 1 - alpha;
    } else if (ftype === "highpass") {
      b0 = (1 + cosw0) / 2; b1 = -(1 + cosw0); b2 = (1 + cosw0) / 2;
      a0 = 1 + alpha; a1 = -2 * cosw0; a2 = 1 - alpha;
    } else if (ftype === "peak") {
      const a = Math.pow(10, gainDb / 40);
      b0 = 1 + alpha * a; b1 = -2 * cosw0; b2 = 1 - alpha * a;
      a0 = 1 + alpha / a; a1 = -2 * cosw0; a2 = 1 - alpha / a;
    } else if (ftype === "low_shelf") {
      const a = Math.pow(10, gainDb / 40);
      const sa = Math.sqrt(a);
      b0 = a * ((a + 1) - (a - 1) * cosw0 + 2 * sa * alpha);
      b1 = 2 * a * ((a - 1) - (a + 1) * cosw0);
      b2 = a * ((a + 1) - (a - 1) * cosw0 - 2 * sa * alpha);
      a0 = (a + 1) + (a - 1) * cosw0 + 2 * sa * alpha;
      a1 = -2 * ((a - 1) + (a + 1) * cosw0);
      a2 = (a + 1) + (a - 1) * cosw0 - 2 * sa * alpha;
    } else if (ftype === "high_shelf") {
      const a = Math.pow(10, gainDb / 40);
      const sa = Math.sqrt(a);
      b0 = a * ((a + 1) + (a - 1) * cosw0 + 2 * sa * alpha);
      b1 = -2 * a * ((a - 1) + (a + 1) * cosw0);
      b2 = a * ((a + 1) + (a - 1) * cosw0 - 2 * sa * alpha);
      a0 = (a + 1) - (a - 1) * cosw0 + 2 * sa * alpha;
      a1 = 2 * ((a - 1) - (a + 1) * cosw0);
      a2 = (a + 1) - (a - 1) * cosw0 - 2 * sa * alpha;
    } else {
      return { b0: 1, b1: 0, b2: 0, a1: 0, a2: 0 };
    }
    const inv = 1 / a0;
    return { b0: b0 * inv, b1: b1 * inv, b2: b2 * inv, a1: a1 * inv, a2: a2 * inv };
  }

  function magDb(c, freq) {
    const w = (2 * Math.PI * freq) / SR;
    const cosw = Math.cos(w), sinw = Math.sin(w);
    const cos2 = Math.cos(2 * w), sin2 = Math.sin(2 * w);
    const reN = c.b0 + c.b1 * cosw + c.b2 * cos2;
    const imN = -(c.b1 * sinw + c.b2 * sin2);
    const reD = 1 + c.a1 * cosw + c.a2 * cos2;
    const imD = -(c.a1 * sinw + c.a2 * sin2);
    const mag = Math.sqrt(reN * reN + imN * imN) / Math.sqrt(reD * reD + imD * imD);
    return 20 * Math.log10(mag + 1e-12);
  }

  function combinedDb(bands, freq) {
    let sum = 0;
    for (const b of bands) sum += magDb(makeCoeffs(b), freq);
    return Math.max(GMIN - 6, Math.min(GMAX + 6, sum));
  }

  function bandNodeGain(b) {
    if (b.type === "highpass" || b.type === "lowpass") return 0;
    return b.gain_db || 0;
  }

  function annotateBands(bands) {
    return (bands || []).map((b, i) => ({
      ...b,
      id: b.id ?? i,
      color: b.color || COLORS[i % COLORS.length],
      q: b.q ?? 0.71,
      gain_db: b.gain_db ?? 0,
    }));
  }

  class EqVisualizer {
    constructor(canvas, opts) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.opts = opts || {};
      this.bands = [];
      this.catalog = {};
      this.preset = "off";
      this.enabled = true;
      this.selected = -1;
      this.speaking = false;
      this.specFrame = [];      // real bands [{f,v}] from the server
      this.specView = new Float32Array(0); // smoothed values for display
      this._drag = null;
      this._saveTimer = null;
      this._anim = 0;

      this._onResize = () => this.resize();
      window.addEventListener("resize", this._onResize);

      canvas.addEventListener("mousedown", (e) => this._pointerDown(e));
      canvas.addEventListener("mousemove", (e) => this._pointerMove(e));
      window.addEventListener("mouseup", () => this._pointerUp());
      canvas.addEventListener("mouseleave", () => this._pointerUp());

      this.resize();
      this._loop = () => {
        this._anim++;
        this.draw();
        requestAnimationFrame(this._loop);
      };
      requestAnimationFrame(this._loop);
    }

    resize() {
      const rect = this.canvas.parentElement.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      const w = Math.max(320, rect.width - 2);
      const h = Math.max(200, rect.height - 2);
      this.canvas.width = w * dpr;
      this.canvas.height = h * dpr;
      this.canvas.style.width = w + "px";
      this.canvas.style.height = h + "px";
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      this.w = w;
      this.h = h;
      this.pad = { l: 44, r: 52, t: 18, b: 28 };
    }

    setCatalog(catalog) {
      this.catalog = catalog || {};
    }

    setPreset(preset, bands) {
      this.preset = preset || "off";
      if (bands) {
        this.bands = annotateBands(bands);
      } else if (this.catalog.bands && this.catalog.bands[preset]) {
        this.bands = annotateBands(this.catalog.bands[preset]);
      } else {
        this.bands = [];
      }
      if (this.selected >= this.bands.length) this.selected = this.bands.length - 1;
      this._notifyBandPanel();
    }

    setEnabled(v) {
      this.enabled = !!v;
    }

    setSpeaking(v) {
      this.speaking = !!v;
    }

    setSpectrumFrame(bands) {
      this.specFrame = Array.isArray(bands) ? bands : [];
      if (this.specView.length !== this.specFrame.length) {
        this.specView = new Float32Array(this.specFrame.length);
      }
    }

    _plotX(freq) {
      const g = this.pad;
      return g.l + logFreq(freq) * (this.w - g.l - g.r);
    }
    _plotY(db) {
      const g = this.pad;
      const t = (db - GMIN) / (GMAX - GMIN);
      return g.t + (1 - t) * (this.h - g.t - g.b);
    }
    _unplotX(x) {
      const g = this.pad;
      return invLogFreq((x - g.l) / (this.w - g.l - g.r));
    }
    _unplotY(y) {
      const g = this.pad;
      return GMIN + (1 - (y - g.t) / (this.h - g.t - g.b)) * (GMAX - GMIN);
    }

    _hitNode(mx, my) {
      for (let i = this.bands.length - 1; i >= 0; i--) {
        const b = this.bands[i];
        const nx = this._plotX(b.freq);
        const ny = this._plotY(bandNodeGain(b));
        if ((mx - nx) ** 2 + (my - ny) ** 2 < 144) return i;
      }
      return -1;
    }

    _pointerDown(e) {
      if (!this.enabled || !this.bands.length) return;
      const r = this.canvas.getBoundingClientRect();
      const mx = e.clientX - r.left;
      const my = e.clientY - r.top;
      const hit = this._hitNode(mx, my);
      if (hit >= 0) {
        this.selected = hit;
        this._drag = { i: hit, mx, my };
        this._notifyBandPanel();
      }
    }

    _pointerMove(e) {
      if (!this._drag) return;
      const r = this.canvas.getBoundingClientRect();
      const mx = e.clientX - r.left;
      const my = e.clientY - r.top;
      const b = this.bands[this._drag.i];
      b.freq = Math.max(FMIN, Math.min(FMAX, this._unplotX(mx)));
      if (b.type !== "highpass" && b.type !== "lowpass") {
        b.gain_db = Math.max(GMIN, Math.min(GMAX, this._unplotY(my)));
      }
      this.preset = "custom";
      this._notifyBandPanel();
      this._scheduleSave();
    }

    _pointerUp() {
      if (this._drag) {
        this._drag = null;
        this._scheduleSave(true);
      }
    }

    _scheduleSave(now) {
      clearTimeout(this._saveTimer);
      const run = () => {
        if (this.opts.onChange) {
          this.opts.onChange({
            preset: "custom",
            bands: this.bands.map(({ type, freq, q, gain_db }) => ({ type, freq, q, gain_db: gain_db || 0 })),
          });
        }
      };
      if (now) run();
      else this._saveTimer = setTimeout(run, 280);
    }

    updateBandParam(key, val) {
      if (this.selected < 0 || !this.bands[this.selected]) return;
      const b = this.bands[this.selected];
      if (key === "freq") b.freq = Math.max(FMIN, Math.min(FMAX, val));
      else if (key === "gain_db") b.gain_db = Math.max(GMIN, Math.min(GMAX, val));
      else if (key === "q") b.q = Math.max(0.1, Math.min(18, val));
      else if (key === "type") b.type = val;
      this.preset = "custom";
      this._scheduleSave(true);
      this._notifyBandPanel();
    }

    _notifyBandPanel() {
      if (this.opts.onSelect) this.opts.onSelect(this.selected, this.bands[this.selected] || null);
    }

    deselect() {
      this.selected = -1;
      this._notifyBandPanel();
    }

    _drawGrid() {
      const ctx = this.ctx;
      const g = this.pad;
      ctx.fillStyle = "#151515";
      ctx.fillRect(0, 0, this.w, this.h);

      const freqs = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000];
      ctx.strokeStyle = "rgba(10,132,255,0.08)";
      ctx.lineWidth = 1;
      freqs.forEach((f) => {
        const x = this._plotX(f);
        ctx.beginPath(); ctx.moveTo(x, g.t); ctx.lineTo(x, this.h - g.b); ctx.stroke();
      });
      for (let db = GMIN; db <= GMAX; db += 3) {
        const y = this._plotY(db);
        ctx.strokeStyle = db === 0 ? "rgba(10,132,255,0.28)" : "rgba(10,132,255,0.06)";
        ctx.beginPath(); ctx.moveTo(g.l, y); ctx.lineTo(this.w - g.r, y); ctx.stroke();
      }

      ctx.fillStyle = "rgba(255,255,255,0.35)";
      ctx.font = "10px Inter, system-ui, sans-serif";
      ctx.textAlign = "center";
      freqs.forEach((f) => {
        const label = f >= 1000 ? (f / 1000) + "k" : String(f);
        ctx.fillText(label, this._plotX(f), this.h - 8);
      });
      ctx.textAlign = "right";
      for (let db = GMIN; db <= GMAX; db += 6) {
        ctx.fillText((db > 0 ? "+" : "") + db, g.l - 6, this._plotY(db) + 3);
      }
      ctx.textAlign = "left";
      ctx.fillStyle = "rgba(255,255,255,0.25)";
      ctx.fillText("dB", this.w - g.r + 6, g.t + 10);
    }

    _drawSpectrum() {
      const frame = this.specFrame;
      const n = frame.length;
      if (n < 2) return;
      if (this.specView.length !== n) this.specView = new Float32Array(n);
      const view = this.specView;

      const ctx = this.ctx;
      const g = this.pad;
      const baseY = this.h - g.b;
      const top = g.t;
      const pts = new Array(n);
      let peak = 0;
      for (let i = 0; i < n; i++) {
        const target = frame[i].v || 0;
        // fast attack, slower release for a lively but stable meter
        const k = target > view[i] ? 0.55 : 0.16;
        view[i] += (target - view[i]) * k;
        if (view[i] > peak) peak = view[i];
        const x = this._plotX(frame[i].f);
        const y = baseY - view[i] * (baseY - top);
        pts[i] = [x, y];
      }
      if (peak < 0.001) return;

      // Filled gradient area under the curve.
      ctx.beginPath();
      ctx.moveTo(pts[0][0], baseY);
      for (let i = 0; i < n; i++) ctx.lineTo(pts[i][0], pts[i][1]);
      ctx.lineTo(pts[n - 1][0], baseY);
      ctx.closePath();
      const grad = ctx.createLinearGradient(0, top, 0, baseY);
      grad.addColorStop(0, "rgba(64,156,255,0.32)");
      grad.addColorStop(1, "rgba(10,132,255,0.02)");
      ctx.fillStyle = grad;
      ctx.fill();

      // Outline.
      ctx.beginPath();
      for (let i = 0; i < n; i++) {
        if (i === 0) ctx.moveTo(pts[i][0], pts[i][1]);
        else ctx.lineTo(pts[i][0], pts[i][1]);
      }
      ctx.strokeStyle = "rgba(90,200,250,0.55)";
      ctx.lineWidth = 1.3;
      ctx.stroke();
    }

    _drawCurve(bands, color, fillAlpha) {
      if (!bands.length) return;
      const ctx = this.ctx;
      const g = this.pad;
      const steps = 240;
      const pts = [];
      for (let i = 0; i <= steps; i++) {
        const freq = invLogFreq(i / steps);
        pts.push([this._plotX(freq), this._plotY(combinedDb(bands, freq))]);
      }
      ctx.beginPath();
      pts.forEach((p, i) => { if (i === 0) ctx.moveTo(p[0], p[1]); else ctx.lineTo(p[0], p[1]); });
      ctx.strokeStyle = color;
      ctx.lineWidth = 2.2;
      ctx.stroke();
      if (fillAlpha) {
        ctx.lineTo(pts[pts.length - 1][0], this._plotY(0));
        ctx.lineTo(pts[0][0], this._plotY(0));
        ctx.closePath();
        ctx.fillStyle = color.replace(")", `, ${fillAlpha})`).replace("rgb", "rgba").replace("#", "");
        const grad = ctx.createLinearGradient(0, g.t, 0, this.h - g.b);
        grad.addColorStop(0, color + "33");
        grad.addColorStop(1, color + "05");
        ctx.fillStyle = grad;
        ctx.fill();
      }
    }

    _drawBandCurve(band) {
      this._drawCurve([band], band.color, 0.12);
    }

    draw() {
      this._drawGrid();
      this._drawSpectrum();
      if (!this.enabled || !this.bands.length) {
        this.ctx.fillStyle = "rgba(142,142,147,0.5)";
        this.ctx.font = "12px Inter, system-ui, sans-serif";
        this.ctx.textAlign = "center";
        this.ctx.fillText(this.enabled ? "Flat — choose a preset above" : "EQ bypassed", this.w / 2, this.h / 2);
        return;
      }
      this._drawCurve(this.bands, "rgba(64,156,255,0.95)", null);
      this.bands.forEach((b, i) => {
        if (i === this.selected) this._drawBandCurve(b);
        const x = this._plotX(b.freq);
        const y = this._plotY(bandNodeGain(b));
        const r = i === this.selected ? 8 : 6;
        this.ctx.beginPath();
        this.ctx.arc(x, y, r, 0, Math.PI * 2);
        this.ctx.fillStyle = b.color;
        this.ctx.fill();
        this.ctx.strokeStyle = i === this.selected ? "#fff" : "rgba(0,0,0,0.45)";
        this.ctx.lineWidth = i === this.selected ? 2 : 1;
        this.ctx.stroke();
      });
    }
  }

  global.EqVisualizer = EqVisualizer;
  global.EQ_UI = { annotateBands, COLORS };
})(window);
