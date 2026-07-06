/** Docs embed demo — real audio + mayaWaveform canvas. */
document.addEventListener("alpine:init", () => {
  const utils = window.mayaWaveformUtils;
  const gen = utils?.generatePeaks ?? (() => []);

  const DEMO_TRACKS = [
    {
      id: 1,
      title: "Denominator",
      artist: "Demo — sine A4",
      genre: "Drum & Bass",
      bpm: 174,
      key: "Db Min",
      duration: 12,
      color: "#00d4a0",
      src: "audio/track1.wav",
      peaks: gen(42),
    },
    {
      id: 2,
      title: "Second Horizon",
      artist: "Demo — sine C#5",
      genre: "Drum & Bass",
      bpm: 172,
      key: "F Min",
      duration: 10,
      color: "#7b6fff",
      src: "audio/track2.wav",
      peaks: gen(17),
    },
    {
      id: 3,
      title: "Turbulance",
      artist: "Demo — sine E5",
      genre: "Drum & Bass",
      bpm: 176,
      key: "G# Min",
      duration: 14,
      color: "#ff6b35",
      src: "audio/track3.wav",
      peaks: gen(88),
    },
  ];

  Alpine.data("mayaPlayerDemo", () => ({
    tracks: DEMO_TRACKS,
    trackIdx: 0,
    playing: false,
    currentTime: 0,
    duration: 0,
    volume: 0.8,
    muted: false,
    queueOpen: false,
    shuffle: false,
    repeat: false,

    get currentTrack() {
      return this.tracks[this.trackIdx] || null;
    },

    get accentColor() {
      return this.currentTrack?.color || "#00d4a0";
    },

    get accentStyle() {
      return { "--accent-active": this.accentColor };
    },

    get volumePct() {
      const v = this.muted ? 0 : this.volume;
      return `${v * 100}%`;
    },

    get volumeDisplay() {
      return Math.round((this.muted ? 0 : this.volume) * 100);
    },

    get remaining() {
      return Math.max(0, (this.duration || this.currentTrack?.duration || 0) - this.currentTime);
    },

    fmtTime(sec) {
      return utils?.fmtTime?.(sec) ?? "0:00";
    },

    init() {
      if (this.currentTrack?.duration) this.duration = this.currentTrack.duration;
      this.$nextTick(() => {
        this._applyVolume();
        const el = this._audio();
        if (el) {
          el.addEventListener("ended", () => {
            if (this.repeat) {
              this.seekMock(0);
              el.play().catch(() => {});
            } else {
              this.next();
            }
          });
        }
      });
    },

    _audio() {
      return this.$refs.audio;
    },

    _applyVolume() {
      const el = this._audio();
      if (!el) return;
      el.volume = Math.min(1, Math.max(0, this.volume));
      el.muted = this.muted;
    },

    _loadAndPlay() {
      const el = this._audio();
      const tr = this.currentTrack;
      if (!el || !tr?.src) return;
      const abs = new URL(tr.src, window.location.href).href;
      if (el.src !== abs) {
        el.src = tr.src;
        this.currentTime = 0;
        this.duration = tr.duration || 0;
      }
      this._applyVolume();
      el.play().catch(() => {});
    },

    togglePlay() {
      const el = this._audio();
      if (!el) return;
      if (this.playing) el.pause();
      else this._loadAndPlay();
    },

    selectTrack(i) {
      if (i < 0 || i >= this.tracks.length) return;
      this.trackIdx = i;
      this.currentTime = 0;
      this.duration = this.tracks[i].duration || 0;
      this._loadAndPlay();
    },

    next() {
      const n = this.shuffle
        ? Math.floor(Math.random() * this.tracks.length)
        : (this.trackIdx + 1) % this.tracks.length;
      this.selectTrack(n);
    },

    prev() {
      if (this.currentTime > 3) {
        this.seekMock(0);
        return;
      }
      const n = this.shuffle
        ? Math.floor(Math.random() * this.tracks.length)
        : (this.trackIdx - 1 + this.tracks.length) % this.tracks.length;
      this.selectTrack(n);
    },

    seekMock(fraction) {
      const el = this._audio();
      const dur = this.duration || el?.duration || this.currentTrack?.duration || 0;
      if (!dur) return;
      const f = Math.min(1, Math.max(0, Number(fraction) || 0));
      const t = f * dur;
      if (el && isFinite(el.duration)) {
        try {
          el.currentTime = t;
        } catch (_) {}
      }
      this.currentTime = t;
    },

    onTime() {
      const el = this._audio();
      if (el) this.currentTime = el.currentTime || 0;
    },

    onMeta() {
      const el = this._audio();
      if (el && isFinite(el.duration)) this.duration = el.duration;
      else if (this.currentTrack?.duration) this.duration = this.currentTrack.duration;
    },

    onPlay() {
      this.playing = true;
    },

    onPause() {
      this.playing = false;
    },

    setVolume(v) {
      this.volume = Math.min(1, Math.max(0, Number(v) || 0));
      if (this.volume > 0) this.muted = false;
      this._applyVolume();
    },

    setVolumePercent(p) {
      this.setVolume(Number(p) / 100);
    },

    toggleMute() {
      this.muted = !this.muted;
      this._applyVolume();
    },

    toggleQueue() {
      this.queueOpen = !this.queueOpen;
    },

    toggleShuffle() {
      this.shuffle = !this.shuffle;
    },

    toggleRepeat() {
      this.repeat = !this.repeat;
    },

    drawQueueMini(el, track, i) {
      if (utils?.drawMini) utils.drawMini(el, track.peaks, i === this.trackIdx, this.$root);
    },
  }));
});
