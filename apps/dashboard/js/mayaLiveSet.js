/**
 * Live-set utilities and YouTube transport for dashboard mayaPlayer.
 * Load before Alpine (see conversation.html).
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
        artist: raw.artist ?? null,
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
      artist: raw.artist ?? null,
      footnote: raw.footnote ?? null,
      isNote: raw.isNote ?? false,
    };
  }

  function createYtTransport(player, { videoId, targetId = "maya-yt-player", fallbackMs = 8000 } = {}) {
    let ytPlayer = null;
    let pollTimer = null;
    let fallbackTimer = null;
    let destroyed = false;
    let expectedTimeAfterSeek = null;

    function isReady() {
      return !destroyed && !!ytPlayer;
    }

    function getPlayerState() {
      return ytPlayer?.getPlayerState?.();
    }

    function clearTimers() {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
      if (fallbackTimer) {
        clearTimeout(fallbackTimer);
        fallbackTimer = null;
      }
    }

    function startPoll() {
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(() => {
        const st = ytPlayer?.getPlayerState?.();
        const YT = window.YT?.PlayerState;
        const ytTime = ytPlayer?.getCurrentTime?.() ?? 0;

        if (st === YT?.PLAYING) {
          // Playing: always trust the embed clock (demo behavior).
          if (expectedTimeAfterSeek !== null && Math.abs(ytTime - expectedTimeAfterSeek) < 2.0) {
            expectedTimeAfterSeek = null;
          }
          player.currentTime = ytTime;
        } else if (expectedTimeAfterSeek === null) {
          // Not playing and no pending seek: sync when YT reports a real position.
          if (st === YT?.PAUSED && ytTime > 0) {
            player.currentTime = ytTime;
          }
        }
        // While expectedTimeAfterSeek is set (cued/unstarted after seek), leave
        // player.currentTime alone so the optimistic value from seekToSeconds holds.

        player._scrollSetTracklist?.();
      }, 500);
    }

    function destroy() {
      destroyed = true;
      clearTimers();
      try {
        ytPlayer?.destroy?.();
      } catch (_) {}
      ytPlayer = null;
    }

    function seekToSeconds(seconds) {
      const sec = Number(seconds) || 0;
      expectedTimeAfterSeek = sec;
      if (ytPlayer?.seekTo) {
        ytPlayer.seekTo(sec, true);
        ytPlayer.playVideo?.();
      }
      player.currentTime = sec;
    }

    function play() {
      if (!ytPlayer) return;
      player.buffering = true;
      ytPlayer.playVideo?.();
    }

    function pause() {
      if (!ytPlayer) return;
      player.buffering = true;
      ytPlayer.pauseVideo?.();
    }

    function unMute() {
      try {
        ytPlayer?.unMute?.();
        player.setMuted = false;
      } catch (_) {}
    }



    function init(onReady, onFallback) {
      if (!videoId) {
        onFallback?.();
        return;
      }

      const activateFallback = () => {
        if (destroyed) return;
        clearTimers();
        onFallback?.();
      };

      const mountPlayer = () => {
        if (fallbackTimer) {
          clearTimeout(fallbackTimer);
          fallbackTimer = null;
        }
        const target = document.getElementById(targetId);
        if (!target) {
          activateFallback();
          return;
        }
        try {
          ytPlayer = new window.YT.Player(targetId, {
            videoId,
            playerVars: {
              modestbranding: 1,
              rel: 0,
              playsinline: 1,
            },
            events: {
              onReady: () => {
                if (destroyed) return;
                player.setYtReady = true;
                if (fallbackTimer) {
                  clearTimeout(fallbackTimer);
                  fallbackTimer = null;
                }
                startPoll();
                onReady?.();
              },
              onError: () => activateFallback(),
              onStateChange: (ev) => {
                if (destroyed) return;
                const YT = window.YT?.PlayerState;
                if (!YT) return;
                if (ev.data === YT.PLAYING) {
                  player.playing = true;
                  player.buffering = false;
                  if (player.setTransportState === "cued") {
                    player.setTransportState = "youtube";
                  }
                } else if (ev.data === YT.PAUSED) {
                  player.playing = false;
                  player.buffering = false;
                } else if (ev.data === YT.BUFFERING) {
                  player.buffering = true;
                } else if (ev.data === YT.ENDED) {
                  player.playing = false;
                  player.buffering = false;
                } else if (ev.data === YT.UNSTARTED || ev.data === YT.CUED) {
                  player.playing = false;
                  player.buffering = false;
                  if (ev.data === YT.CUED) {
                    player.setTransportState = "cued";
                  }
                }
              },
            },
          });
          // Player constructed successfully — wait for its own onReady/onError
          // rather than the blind mount timeout (a real YouTube video can take
          // more than a few seconds to signal ready under load). Keep a longer
          // safety net so a genuinely stuck player still falls back.
          if (fallbackTimer) clearTimeout(fallbackTimer);
          fallbackTimer = setTimeout(() => {
            if (!player.setYtReady) activateFallback();
          }, 10000);
        } catch (_) {
          activateFallback();
        }
      };

      if (window.YT?.Player) {
        mountWhenReady(mountPlayer, activateFallback, { maxAttempts: 300 });
      } else if (!document.querySelector('script[src*="youtube.com/iframe_api"]')) {
        const tag = document.createElement("script");
        tag.src = "https://www.youtube.com/iframe_api";
        document.head.appendChild(tag);
        const prev = window.onYouTubeIframeAPIReady;
        window.onYouTubeIframeAPIReady = () => {
          prev?.();
          mountWhenReady(mountPlayer, activateFallback, { maxAttempts: 300 });
        };
      } else {
        const waitYt = setInterval(() => {
          if (window.YT?.Player) {
            clearInterval(waitYt);
            mountWhenReady(mountPlayer, activateFallback, { maxAttempts: 300 });
          }
        }, 100);
      }

      fallbackTimer = setTimeout(() => {
        if (!player.setYtReady) activateFallback();
      }, fallbackMs);
    }

    return { init, destroy, seekToSeconds, play, pause, unMute, isReady, getPlayerState };
  }

  function mountWhenReady(mountPlayer, onGiveUp, { targetId = "maya-yt-player", maxAttempts = 40 } = {}) {
    let attempts = 0;
    let mounted = false;
    const tryMount = () => {
      if (mounted) return;
      const el = document.getElementById(targetId);
      if (el) {
        mounted = true;
        mountPlayer();
        return;
      }
      attempts += 1;
      if (attempts >= maxAttempts) {
        onGiveUp?.();
        return;
      }
      requestAnimationFrame(tryMount);
    };
    // rAF may not fire in headless browsers — poll with setTimeout as well.
    const poll = setInterval(() => {
      if (mounted) {
        clearInterval(poll);
        return;
      }
      tryMount();
      if (mounted || attempts >= maxAttempts) clearInterval(poll);
    }, 50);
    requestAnimationFrame(tryMount);
  }

  window.mayaLiveSetUtils = {
    parseTime,
    fmtSetTime,
    currentEntryIndex,
    buildTrackNumbers,
    normalizeEntry,
    EQ_HEIGHTS,
  };

  window.mayaSetYtTransport = { create: createYtTransport, mountWhenReady };
})();
