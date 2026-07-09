/**
 * Portable Alpine.js live set viewer — YouTube embed + synced tracklist.
 *
 * Load order:
 *   1. tokens.css
 *   2. live-set-demo.css (or dashboard styles)
 *   3. mayaLiveSet.js  (before Alpine)
 *   4. youtube iframe_api (optional)
 *   5. alpine.min.js
 *   6. live-set-demo.js (optional)
 *
 * Dashboard integration:
 *   Bind currentTime from $store.mayaPlayer when mode === 'live_set'.
 *   Call seekToSeconds() instead of YT.Player directly.
 */
(function () {
  const EQ_HEIGHTS = [0.5, 1, 0.65, 0.85, 0.45];

  function parseTime(s) {
    const parts = String(s || "")
      .split(":")
      .map(Number);
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    return parts[0] * 60 + parts[1];
  }

  function fmtSetTime(sec) {
    const s = Math.max(0, Math.floor(Number(sec) || 0));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const r = s % 60;
    if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
    return `${m}:${String(r).padStart(2, "0")}`;
  }

  function currentEntryIndex(entries, currentTime) {
    let idx = -1;
    for (let i = 0; i < entries.length; i++) {
      const start = entries[i].start_seconds ?? entries[i].startSec ?? 0;
      if (currentTime >= start) idx = i;
    }
    return idx;
  }

  function buildTrackNumbers(entries) {
    let n = 0;
    return entries.map((e) => {
      const isNarrative = e.attrs?.is_narrative ?? e.isNote ?? false;
      return isNarrative ? null : ++n;
    });
  }

  function normalizeEntry(raw, i) {
    if (raw.start_seconds != null) {
      return {
        id: raw.id ?? i,
        position: raw.position ?? i + 1,
        timestamp: raw.timestamp || fmtSetTime(raw.start_seconds),
        start_seconds: raw.start_seconds,
        startSec: raw.start_seconds,
        label: raw.label || raw.title || "",
        title: raw.title || raw.label || "",
        footnote: raw.attrs?.footnote ?? raw.footnote ?? null,
        isNote: raw.attrs?.is_narrative ?? raw.isNote ?? false,
      };
    }
    return {
      id: raw.id ?? i,
      position: raw.position ?? i + 1,
      timestamp: raw.timestamp,
      start_seconds: raw.startSec,
      startSec: raw.startSec,
      label: raw.title || raw.label || "",
      title: raw.title || raw.label || "",
      footnote: raw.footnote ?? null,
      isNote: raw.isNote ?? false,
    };
  }

  function entriesFromRaw(rawRows) {
    return rawRows.map(([ts, title, footnote, isNote], i) =>
      normalizeEntry(
        {
          id: i,
          timestamp: ts,
          startSec: parseTime(ts),
          title,
          footnote,
          isNote: isNote ?? false,
        },
        i,
      ),
    );
  }

  const FRED_USB002_RAW = [
    ["0:01", "Mythologies: X. L'Accouchement x My House",
      "Me n Thomas spent the week in London preparing a whole load of things so we had a usb stacked with ideas… this first 3 minutes right here, ive never felt calmer in my life, knowing that what was about to happen was…"],
    ["3:16", "One More Time x We've Lost Dancing x Ain't No Mountain High Enough", "... this ^"],
    ["7:37", "Hackney Pigeon (Sammy Virji VIP) — Tessela",
      "Shoutout the uk, the only place to go after that song I thought, shoutout ed from overmono aka tessela"],
    ["11:30", "Rollin' & Scratchin' x Spinal Scratch x 808 State x Baby again.. x Rumble x Renegade Master"],
    ["14:18", "Iconic Vocals",
      "It was mad hearing these iconicccc vocals, like the my house vocal from the beginning, or this one, but played by Thomas, it gives them a sorta even deeper resonance", true],
    ["16:20", "LFO — LFO"],
    ["17:40", "Crescendolls — Daft Punk (MPH edit)",
      "Shoutout busy p and Thomas's son looming in the background. ed banger forever"],
    ["20:00", "Technologic x stop&watch x Pulse Z x Needle Guy x Circles",
      "We made about 20 versions of technologic mashed up wit different things, but this was the one that I decided to play. Shoutout cu.rve."],
    ["22:34", "Technologic x Needle Guy", "Ok we played two…"],
    ["24:05", "Technologic x Circles", "Okay we played three"],
    ["25:00", "Contact x My Girls x Night Vision (The Twelves Cover)"],
    ["31:10", "Doin' it Right x places to be (Clipz Remix)"],
    ["36:04", "I remember! my eye caught this group of friends who were jus all facing each other shouting every word it was beautiful to see",
      undefined, true],
    ["40:00", "Clubbed To Death (Kurayamino Variation) x The Revolution Will Not Be Televised"],
    ["41:45", "Yeah! — Usher",
      "I remember I looked down at the decks and saw the track was called 'revolution yeah'. I thought I wonder what the 'yeah' means…. Yeah!"],
    ["43:49", "Serious Sounds (VIP) — Pascal"],
    ["45:25", "Touch — Daft Punk"],
    ["47:10", "Giorgio by Moroder — Daft Punk",
      "Big hennnn, this is OUR daft punk record I think ❤"],
    ["48:45", "Digital Loving Arms",
      "One of the things that brought me indescribable joy this night, was seeing Thomas's son singing along to every song of his dads. he was like 1 when they last played."],
    ["54:14", "Raspberry Beret — Prince"],
    ["57:20", "Teachers x flight fm x Southside",
      "Shoutout joy Orbison man, for a crowd to look like this just at like the hi hat intro of a song?!"],
    ["1:01:00", "Turn On The Lights again.. x Harder, Better, Faster, Stronger"],
    ["1:06:30", "Aerodynamic x Victory Lap Five"],
    ["1:09:07", "Starboy x leavemealone",
      "My brother texted me like an hour before the show being like 'is it just me or are starboy and leavemealone like the same but in different universes'."],
    ["1:11:20", "leavemealone (Nia Archives Remix Freddit)"],
    ["1:18:20", "Music Sounds Better With You — Stardust",
      "We wanted to build up each of the parts in the machine, and then gradually the machine finds its soul"],
    ["1:28:20", "Da Funk (Armand van Helden 'Ten Minutes Of Funk' Mix) x 2009 x ICEY.."],
    ["1:32:45", "Never the End x Can't Do Without You",
      "Oh Jesus Christ. This was maybe the most beautiful thing ive ever seen happen. Thats Thomas's son singing in a song he made when he was 12, blended with Thomas playing (saying?) i cant do without u"],
    ["1:36:00", "Signatune (Thomas Bangalter edit) x Around the World"],
    ["1:39:40", "Delilah (pull me out of this)", "Shoutout ally pally Every. Single. Time."],
    ["1:46:06", "One More Time x just stand there x Femi",
      "To everyone whos been a part of USB002, everyone who came thru around the world, everyone who made it what it was, thank you forever"],
  ];

  const FRED_USB002_ENTRIES = entriesFromRaw(FRED_USB002_RAW);

  const FRED_USB002_SET = {
    mode: "live_set",
    set_id: "USB002",
    title: "Fred again.. & Thomas Bangalter",
    venue: "Alexandra Palace, London",
    date: "27 Feb 2026",
    video_id: "gfF8jzBVWvM",
    container_url: "https://www.youtube.com/watch?v=gfF8jzBVWvM",
    duration_seconds: 6918,
    duration_label: "1:55:18",
    entries: FRED_USB002_ENTRIES,
    linked_sets: [
      {
        schema_id: "1001tl",
        external_id: "2gu8q2xk",
        url: "https://www.1001tracklists.com/tracklist/2gu8q2xk/fred-again..-thomas-bangalter-usb002-alexandra-palace-london-united-kingdom-2026-02-27.html",
      },
      {
        schema_id: "apple_music",
        external_id: "1890298647",
        url: "https://music.apple.com/us/album/alexandra-palace-london-feb-27-2026-dj-mix/1890298647",
      },
    ],
  };

  window.mayaLiveSetUtils = {
    parseTime,
    fmtSetTime,
    currentEntryIndex,
    buildTrackNumbers,
    normalizeEntry,
    entriesFromRaw,
    EQ_HEIGHTS,
  };

  window.FRED_USB002_ENTRIES = FRED_USB002_ENTRIES;
  window.FRED_USB002_SET = FRED_USB002_SET;

  function registerAlpine() {
    Alpine.data("mayaLiveSet", (liveSetConfig) => ({
      liveSet: null,
      entries: [],
      currentTime: 0,
      playerReady: false,
      demoMode: false,
      expandedFootnote: null,
      accentColor: "#00d4a0",

      _ytPlayer: null,
      _pollTimer: null,
      _demoTimer: null,
      _fallbackTimer: null,
      _ytTargetId: "yt-player",

      get accentStyle() {
        return { "--accent-active": this.accentColor };
      },

      get currentIdx() {
        return currentEntryIndex(this.entries, this.currentTime);
      },

      get currentEntry() {
        return this.currentIdx >= 0 ? this.entries[this.currentIdx] : null;
      },

      get trackNumbers() {
        return buildTrackNumbers(this.entries);
      },

      get trackCount() {
        return this.entries.filter((e) => !e.isNote).length;
      },

      get setDuration() {
        const d = this.liveSet?.duration_seconds;
        if (d) return d;
        const last = this.entries[this.entries.length - 1];
        return last ? (last.start_seconds ?? last.startSec) + 300 : 1;
      },

      get progressPct() {
        return Math.min(100, (this.currentTime / this.setDuration) * 100);
      },

      get milestoneEntries() {
        return this.entries.filter((_, i) => i % 4 === 0);
      },

      init() {
        const cfg = liveSetConfig || window.FRED_USB002_SET;
        this.loadLiveSet(cfg);
        this._initYoutube();
        this.$watch("currentIdx", () => this._scrollToCurrent());
      },

      destroy() {
        this._clearTimers();
        this._ytPlayer?.destroy?.();
        this._ytPlayer = null;
      },

      loadLiveSet(artifact) {
        this.liveSet = artifact;
        this.entries = (artifact.entries || []).map((e, i) => normalizeEntry(e, i));
        this.accentColor = artifact.accent || "#00d4a0";
        this.expandedFootnote = null;
        this.currentTime = 0;
      },

      fmtTime(sec) {
        return fmtSetTime(sec);
      },

      entryStart(entry) {
        return entry.start_seconds ?? entry.startSec ?? 0;
      },

      isPlayed(i) {
        return i < this.currentIdx;
      },

      isCurrent(i) {
        return i === this.currentIdx;
      },

      toggleFootnote(i) {
        this.expandedFootnote = this.expandedFootnote === i ? null : i;
      },

      seekToSeconds(seconds) {
        const sec = Number(seconds) || 0;
        if (this._ytPlayer?.seekTo) {
          this._ytPlayer.seekTo(sec, true);
          this._ytPlayer.playVideo?.();
        }
        this.currentTime = sec;
      },

      onRowClick(entry, i) {
        if (entry.isNote) return;
        this.seekToSeconds(this.entryStart(entry));
      },

      milestoneLeft(entry) {
        const start = this.entryStart(entry);
        return `${(start / this.setDuration) * 100}%`;
      },

      eqDelay(i) {
        return `${0.38 + i * 0.11}s`;
      },

      _initYoutube() {
        const videoId = this.liveSet?.video_id;
        if (!videoId) {
          this._activateDemoMode();
          return;
        }

        const initPlayer = () => {
          try {
            this._ytPlayer = new window.YT.Player(this._ytTargetId, {
              videoId,
              playerVars: { modestbranding: 1, rel: 0 },
              events: {
                onReady: () => {
                  this.playerReady = true;
                  this._startPoll();
                  if (this._fallbackTimer) {
                    clearTimeout(this._fallbackTimer);
                    this._fallbackTimer = null;
                  }
                },
                onError: () => this._activateDemoMode(),
              },
            });
          } catch (_) {
            this._activateDemoMode();
          }
        };

        if (window.YT?.Player) {
          initPlayer();
        } else if (!document.querySelector('script[src*="youtube.com/iframe_api"]')) {
          const tag = document.createElement("script");
          tag.src = "https://www.youtube.com/iframe_api";
          document.head.appendChild(tag);
          window.onYouTubeIframeAPIReady = initPlayer;
        } else {
          const waitYt = setInterval(() => {
            if (window.YT?.Player) {
              clearInterval(waitYt);
              initPlayer();
            }
          }, 100);
        }

        this._fallbackTimer = setTimeout(() => {
          if (!this.playerReady) this._activateDemoMode();
        }, 4000);
      },

      _startPoll() {
        if (this._pollTimer) clearInterval(this._pollTimer);
        this._pollTimer = setInterval(() => {
          const t = this._ytPlayer?.getCurrentTime?.() ?? 0;
          this.currentTime = t;
        }, 500);
      },

      _activateDemoMode() {
        if (this.demoMode) return;
        this.demoMode = true;
        if (this._pollTimer) {
          clearInterval(this._pollTimer);
          this._pollTimer = null;
        }
        if (this._demoTimer) clearInterval(this._demoTimer);
        const lastStart = this.entries.length
          ? this.entryStart(this.entries[this.entries.length - 1])
          : 0;
        this._demoTimer = setInterval(() => {
          const next = this.currentTime + 4;
          this.currentTime = next > lastStart + 300 ? 0 : next;
        }, 250);
      },

      _clearTimers() {
        if (this._pollTimer) clearInterval(this._pollTimer);
        if (this._demoTimer) clearInterval(this._demoTimer);
        if (this._fallbackTimer) clearTimeout(this._fallbackTimer);
      },

      _scrollToCurrent() {
        const idx = this.currentIdx;
        if (idx < 0) return;
        const list = this.$refs.tracklist;
        const row = list?.querySelector(`[data-track-idx="${idx}"]`);
        if (!list || !row) return;
        const listRect = list.getBoundingClientRect();
        const rowRect = row.getBoundingClientRect();
        const visible = rowRect.top >= listRect.top && rowRect.bottom <= listRect.bottom;
        if (!visible) row.scrollIntoView({ behavior: "smooth", block: "center" });
      },
    }));
  }

  if (window.Alpine) {
    registerAlpine();
  } else {
    document.addEventListener("alpine:init", registerAlpine);
  }
})();
