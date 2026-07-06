/**
 * Portable Alpine.js music player reference — waveform canvas + color-blocking shell.
 *
 * Canonical copy: docs/quartz/static/player-demo/mayaWaveform.js
 * Dashboard copy: apps/dashboard/js/mayaWaveform.js
 *
 * Load order:
 *   1. tokens.css
 *   2. alpine.min.js
 *   3. mayaWaveform.js
 *
 * Playback position uses requestAnimationFrame + wall-clock interpolation
 * between sparse audio timeupdate events (not Alpine reactivity).
 */
(function () {
  function generatePeaks(seed, count = 200) {
    const peaks = [];
    let v = (seed * 9301 + 49297) % 233280;
    const rng = () => {
      v = (v * 9301 + 49297) % 233280;
      return v / 233280;
    };

    let prev = 0.5;
    for (let i = 0; i < count; i++) {
      prev = Math.max(0.05, Math.min(1, prev + (rng() - 0.5) * 0.35));
      peaks.push(prev);
    }

    const introEnd = Math.floor(count * 0.12);
    const breakdown = Math.floor(count * 0.48);
    const breakdownEnd = Math.floor(count * 0.58);
    const outro = Math.floor(count * 0.88);

    for (let i = 0; i < introEnd; i++) peaks[i] *= 0.35 + (i / introEnd) * 0.4;
    for (let i = breakdown; i < breakdownEnd; i++) {
      const t = (i - breakdown) / (breakdownEnd - breakdown);
      peaks[i] *= 0.15 + Math.sin(t * Math.PI) * 0.1;
    }
    for (let i = outro; i < count; i++) {
      peaks[i] *= 1 - ((i - outro) / (count - outro)) * 0.85;
    }
    for (let i = 0; i < count; i++) peaks[i] = Math.max(0.04, peaks[i]);

    return peaks;
  }

  const MOCK_TRACKS = [
    {
      id: 1,
      title: "Denominator",
      artist: "Current Value",
      album: "Holodeck",
      bpm: 174,
      key: "Db Min",
      genre: "Drum & Bass",
      duration: 301,
      peaks: generatePeaks(42),
      color: "#00d4a0",
    },
    {
      id: 2,
      title: "Second Horizon",
      artist: "Current Value",
      album: "Holodeck",
      bpm: 172,
      key: "F Min",
      genre: "Drum & Bass",
      duration: 278,
      peaks: generatePeaks(17),
      color: "#7b6fff",
    },
    {
      id: 3,
      title: "Turbulance",
      artist: "Current Value",
      album: "Holodeck",
      bpm: 176,
      key: "G# Min",
      genre: "Drum & Bass",
      duration: 334,
      peaks: generatePeaks(88),
      color: "#ff6b35",
    },
  ];

  function blockColor(el, name) {
    if (!el) return "";
    return getComputedStyle(el).getPropertyValue(name).trim();
  }

  function fmtTime(sec) {
    const s = Math.max(0, Math.floor(Number(sec) || 0));
    if (!isFinite(s)) return "0:00";
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${m}:${String(r).padStart(2, "0")}`;
  }

  function drawMini(container, peaks, active, tokenRoot) {
    if (!container || !peaks?.length) return;
    const accent = blockColor(tokenRoot, "--block-accent");
    const muted = blockColor(tokenRoot, "--block-muted-bg");
    container.replaceChildren();
    const step = Math.max(1, Math.floor(peaks.length / 12));
    for (let j = 0; j < peaks.length; j += step) {
      const bar = document.createElement("div");
      bar.style.flex = "1";
      bar.style.height = `${Math.max(15, peaks[j] * 100)}%`;
      bar.style.background = active ? accent : muted;
      bar.style.borderRadius = "1px";
      container.appendChild(bar);
    }
  }

  document.addEventListener("alpine:init", () => {
    Alpine.data("mayaWaveform", () => ({
      hoverProgress: null,
      _ro: null,
      _unwatchHover: null,
      _unwatchProgress: null,
      _stopRaf: null,
      _audioEl: null,
      _audioListeners: null,

      get tokenRoot() {
        return this.$el.closest(".player-root") || this.$el;
      },

      _shellData() {
        let el = this.$el.parentElement;
        while (el) {
          const stack = el._x_dataStack;
          if (stack?.length) {
            const d = stack[stack.length - 1];
            if (d?.tracks) return d;
          }
          el = el.parentElement;
        }
        return null;
      },

      _findAudio() {
        return (
          document.getElementById("maya-player-audio") ||
          this.$el.closest(".player-root")?.querySelector("audio") ||
          null
        );
      },

      get peaks() {
        const store = Alpine.store("mayaPlayer");
        if (store?.currentTrack?.peaks?.length) return store.currentTrack.peaks;
        const shell = this._shellData();
        if (shell?.currentTrack?.peaks?.length) return shell.currentTrack.peaks;
        return MOCK_TRACKS[0].peaks;
      },

      get progress() {
        const store = Alpine.store("mayaPlayer");
        if (store && store.duration > 0) return store.progress;
        const shell = this._shellData();
        if (shell?.duration > 0) return shell.currentTime / shell.duration;
        return shell?.mockProgress ?? 0;
      },

      init() {
        this.$nextTick(() => {
          const canvas = this.$refs.canvas;
          if (!canvas) return;

          let lastKnownTime = 0;
          let lastUpdateAt = 0;
          let rafId = null;

          const audio = this._findAudio();
          this._audioEl = audio;

          const syncAnchor = () => {
            if (!audio) return;
            lastKnownTime = audio.currentTime || 0;
            lastUpdateAt = performance.now();
          };

          const interpolatedProgress = () => {
            const store = Alpine.store("mayaPlayer");
            const shell = this._shellData();
            const dur =
              (audio?.duration > 0 && isFinite(audio.duration) ? audio.duration : 0) ||
              store?.duration ||
              shell?.duration ||
              0;
            if (!dur || !isFinite(dur)) {
              if (store?.duration > 0) return store.progress;
              if (shell?.duration > 0) return shell.currentTime / shell.duration;
              return shell?.mockProgress ?? 0;
            }
            if (audio && !audio.paused) {
              const elapsed = (performance.now() - lastUpdateAt) / 1000;
              const estimated = lastKnownTime + elapsed * (audio.playbackRate || 1);
              return Math.min(1, Math.max(0, estimated / dur));
            }
            if (store?.duration > 0) {
              return Math.min(1, Math.max(0, (store.currentTime ?? lastKnownTime) / dur));
            }
            if (shell?.duration > 0) return shell.currentTime / shell.duration;
            return shell?.mockProgress ?? 0;
          };

          this._interpolatedProgress = interpolatedProgress;

          const rafLoop = () => {
            rafId = requestAnimationFrame(rafLoop);
            this.draw(interpolatedProgress());
          };

          this._stopRaf = () => {
            if (rafId != null) cancelAnimationFrame(rafId);
            rafId = null;
          };

          this.draw(interpolatedProgress());

          this._ro = new ResizeObserver(() => this.draw(this._interpolatedProgress?.()));
          this._ro.observe(canvas);

          this._unwatchHover = this.$watch("hoverProgress", () => {
            this.draw(this._interpolatedProgress?.() ?? this.progress);
          });

          if (audio) {
            syncAnchor();
            const listeners = [
              ["timeupdate", syncAnchor],
              ["seeked", syncAnchor],
              ["play", syncAnchor],
            ];
            this._audioListeners = listeners;
            for (const [ev, fn] of listeners) audio.addEventListener(ev, fn);
            rafLoop();
          } else {
            this._unwatchProgress = this.$watch(() => this.progress, () => this.draw());
          }
        });
      },

      destroy() {
        this._stopRaf?.();
        this._stopRaf = null;
        this._ro?.disconnect();
        this._ro = null;
        if (this._audioEl && this._audioListeners) {
          for (const [ev, fn] of this._audioListeners) {
            this._audioEl.removeEventListener(ev, fn);
          }
        }
        this._audioEl = null;
        this._audioListeners = null;
        if (typeof this._unwatchHover === "function") this._unwatchHover();
        this._unwatchHover = null;
        if (typeof this._unwatchProgress === "function") this._unwatchProgress();
        this._unwatchProgress = null;
        this._interpolatedProgress = null;
      },

      draw(progressOverride) {
        const canvas = this.$refs.canvas;
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;

        const root = this.tokenRoot;
        const accent = blockColor(root, "--block-accent");
        const accentHover = blockColor(root, "--block-accent-hover");
        const mutedBg = blockColor(root, "--block-muted-bg");
        const playhead = blockColor(root, "--player-fg");

        const dpr = window.devicePixelRatio || 1;
        const w = canvas.offsetWidth;
        const h = canvas.offsetHeight;
        if (w <= 0 || h <= 0) return;

        canvas.width = w * dpr;
        canvas.height = h * dpr;
        ctx.scale(dpr, dpr);
        ctx.clearRect(0, 0, w, h);

        const peaks = this.peaks;
        const progress =
          progressOverride != null
            ? progressOverride
            : this._interpolatedProgress?.() ?? this.progress;
        const hoverProgress = this.hoverProgress;
        const barCount = peaks.length;
        const barW = w / barCount;
        const gap = Math.max(0.5, barW * 0.18);
        const mid = h / 2;

        for (let i = 0; i < barCount; i++) {
          const peak = peaks[i];
          const barH = Math.max(2, peak * (h * 0.88));
          const x = i * barW;
          const pct = i / barCount;

          let fillColor;
          if (hoverProgress !== null && pct <= hoverProgress) {
            fillColor = pct <= progress ? accent : accentHover;
          } else if (pct <= progress) {
            fillColor = accent;
          } else {
            fillColor = mutedBg;
          }

          ctx.fillStyle = fillColor || mutedBg;
          ctx.fillRect(x, mid - barH / 2, barW - gap, barH);
        }

        if (progress > 0) {
          const px = progress * w;
          ctx.fillStyle = playhead || "#ffffff";
          ctx.fillRect(px - 1, 0, 2, h);
        }
      },

      onClick(e) {
        const canvas = this.$refs.canvas;
        if (!canvas) return;
        const rect = canvas.getBoundingClientRect();
        const fraction = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
        this.$dispatch("waveform-seek", { fraction });
        const store = Alpine.store("mayaPlayer");
        if (store?.seekTo) store.seekTo(fraction);
        else {
          const shell = this._shellData();
          if (shell?.seekMock) shell.seekMock(fraction);
        }
      },

      onMouseMove(e) {
        const canvas = this.$refs.canvas;
        if (!canvas) return;
        const rect = canvas.getBoundingClientRect();
        this.hoverProgress = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
      },
    }));

    Alpine.data("mayaVolumeControl", () => ({
      isEditing: false,
      trayOpen: false,

      toggleTray() {
        this.trayOpen = !this.trayOpen;
        if (!this.trayOpen) this.isEditing = false;
      },

      _source() {
        const store = Alpine.store("mayaPlayer");
        if (store?.active) return store;
        const root = this.$root?._x_dataStack?.[0];
        if (root?.setVolume) return root;
        return store;
      },

      get volume() {
        const s = this._source();
        return Math.round((s.muted ? 0 : s.volume) * 100);
      },

      get isMuted() {
        const s = this._source();
        return s.muted || s.volume === 0;
      },

      setVolumePercent(p) {
        const s = this._source();
        const n = Math.min(100, Math.max(0, Number(p) || 0));
        if (typeof s.setVolumePercent === "function") s.setVolumePercent(n);
        else s.setVolume(n / 100);
      },

      toggleMute() {
        this._source().toggleMute();
      },

      startEditing() {
        this.isEditing = true;
        this.$nextTick(() => {
          this.$refs.volInput?.focus();
          this.$refs.volInput?.select();
        });
      },

      finishEditing() {
        this.isEditing = false;
      },
    }));

    Alpine.data("mayaPlayerShell", (opts = {}) => ({
      layout: opts.layout || "compact",
      trackIdx: 0,
      playing: false,
      currentTime: 0,
      volume: 0.8,
      muted: false,
      queueOpen: false,
      shuffle: false,
      repeat: false,
      mockProgress: 0.35,
      tracks: MOCK_TRACKS,
      _timer: null,

      get presetClass() {
        return this.layout === "hero" ? "preset-hero" : "preset-compact";
      },

      get currentTrack() {
        return this.tracks[this.trackIdx] || null;
      },

      get duration() {
        return this.currentTrack?.duration || 0;
      },

      get accentColor() {
        const store = Alpine.store("mayaPlayer");
        if (store?.currentTrack?.color) return store.currentTrack.color;
        return this.currentTrack?.color || "#00d4a0";
      },

      get accentStyle() {
        return { "--accent-active": this.accentColor };
      },

      get volumePct() {
        const v = this.muted ? 0 : this.volume;
        return `${v * 100}%`;
      },

      fmtTime(sec) {
        return fmtTime(sec);
      },

      init() {
        if (Alpine.store("mayaPlayer")) return;
        this._timer = setInterval(() => {
          if (!this.playing || !this.duration) return;
          this.currentTime = Math.min(this.duration, this.currentTime + 0.25);
          this.mockProgress = this.currentTime / this.duration;
          if (this.currentTime >= this.duration) {
            if (this.repeat) {
              this.currentTime = 0;
              this.mockProgress = 0;
            } else {
              this.next();
            }
          }
        }, 250);
      },

      destroy() {
        if (this._timer) clearInterval(this._timer);
        this._timer = null;
      },

      togglePlay() {
        this.playing = !this.playing;
      },

      next() {
        const n = this.shuffle
          ? Math.floor(Math.random() * this.tracks.length)
          : (this.trackIdx + 1) % this.tracks.length;
        this.selectTrack(n);
      },

      prev() {
        if (this.currentTime > 3) {
          this.currentTime = 0;
          this.mockProgress = 0;
          return;
        }
        const n = this.shuffle
          ? Math.floor(Math.random() * this.tracks.length)
          : (this.trackIdx - 1 + this.tracks.length) % this.tracks.length;
        this.selectTrack(n);
      },

      selectTrack(i) {
        if (i < 0 || i >= this.tracks.length) return;
        this.trackIdx = i;
        this.currentTime = 0;
        this.mockProgress = 0;
        this.playing = true;
      },

      seekMock(fraction) {
        if (!this.duration) return;
        const f = Math.min(1, Math.max(0, Number(fraction) || 0));
        this.currentTime = f * this.duration;
        this.mockProgress = f;
      },

      setVolume(v) {
        this.volume = Math.min(1, Math.max(0, Number(v) || 0));
        if (this.volume > 0) this.muted = false;
      },

      toggleMute() {
        this.muted = !this.muted;
      },

      toggleQueue() {
        this.queueOpen = !this.queueOpen;
      },

      drawQueueMini(el, track, i) {
        drawMini(el, track.peaks, i === this.trackIdx, this.$root);
      },
    }));
  });

  window.mayaWaveformUtils = { generatePeaks, drawMini, fmtTime, MOCK_TRACKS };
})();
