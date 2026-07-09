/**
 * Browser screen/window capture for Maya vision turns.
 * Uses getDisplayMedia; pushes JPEG frames to the server stash.
 */
(function () {
  const PUSH_INTERVAL_MS = 2000;
  const MAX_WIDTH = 1280;
  const GAME_MAX_WIDTH = 640;

  const state = {
    active: false,
    label: "",
    lastSentAt: 0,
    error: "",
    _stream: null,
    _video: null,
    _canvas: null,
    _timer: null,
    _intervalMs: PUSH_INTERVAL_MS,
    _gameMode: false,
    _listeners: new Set(),
  };

  function notify() {
    for (const fn of state._listeners) {
      try {
        fn({ ...state });
      } catch (_) {}
    }
    window.dispatchEvent(new CustomEvent("maya-vision-state", { detail: { ...state } }));
  }

  function setError(msg) {
    state.error = msg || "";
    notify();
  }

  function ensureElements() {
    if (!state._video) {
      state._video = document.createElement("video");
      state._video.muted = true;
      state._video.playsInline = true;
      state._video.setAttribute("playsinline", "");
      state._video.style.cssText = "position:fixed;opacity:0;pointer-events:none;width:1px;height:1px;";
      document.body.appendChild(state._video);
    }
    if (!state._canvas) {
      state._canvas = document.createElement("canvas");
    }
  }

  function frameFromVideo(maxWidth) {
    const video = state._video;
    if (!video || video.readyState < 2 || !video.videoWidth) return null;
    const cap = maxWidth || (state._gameMode ? GAME_MAX_WIDTH : MAX_WIDTH);
    const scale = Math.min(1, cap / video.videoWidth);
    const w = Math.max(1, Math.round(video.videoWidth * scale));
    const h = Math.max(1, Math.round(video.videoHeight * scale));
    const canvas = state._canvas;
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(video, 0, 0, w, h);
    return canvas.toDataURL("image/png");
  }

  async function pushFrame() {
    if (!state.active || !state._video || !state._stream) return;
    const dataUrl = frameFromVideo();
    if (!dataUrl) return;
    const base64 = dataUrl.split(",")[1] || "";
    if (!base64) return;

    try {
      const url = state._gameMode ? "/api/game/frame" : "/api/voice/agent/vision/frame";
      const body = { image: base64, label: state.label };
      if (state._gameMode) {
        body.session_id = "browser_share";
      }
      const r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await r.json();
      if (!data.ok) {
        setError(data.error || "Frame upload failed");
        return;
      }
      state.lastSentAt = Date.now();
      state.error = "";
      notify();
    } catch (exc) {
      setError(String(exc?.message || exc));
    }
  }

  function stopTimer() {
    if (state._timer) {
      clearInterval(state._timer);
      state._timer = null;
    }
  }

  async function cleanup(notifyServer) {
    stopTimer();
    if (state._stream) {
      for (const track of state._stream.getTracks()) {
        try {
          track.stop();
        } catch (_) {}
      }
      state._stream = null;
    }
    if (state._video) {
      state._video.srcObject = null;
    }
    const wasActive = state.active;
    state.active = false;
    state.label = "";
    state._gameMode = false;
    state._intervalMs = PUSH_INTERVAL_MS;
    notify();
    if (notifyServer && wasActive) {
      try {
        await fetch("/api/voice/agent/vision/stop", { method: "POST" });
      } catch (_) {}
    }
  }

  async function startShare(opts) {
    const options = opts && typeof opts === "object" ? opts : {};
    if (state.active) return { ok: true };
    if (!navigator.mediaDevices?.getDisplayMedia) {
      const msg = "Screen sharing is not supported in this browser.";
      setError(msg);
      return { ok: false, error: msg };
    }
    state._intervalMs = Number(options.intervalMs) || PUSH_INTERVAL_MS;
    state._gameMode = !!options.gameMode;
    ensureElements();
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: { cursor: "never" },
        audio: false,
      });
      state._stream = stream;
      state._video.srcObject = stream;
      await state._video.play();

      const track = stream.getVideoTracks()[0];
      state.label = track?.label || "Screen";
      state.active = true;
      state.error = "";
      state.lastSentAt = 0;
      notify();

      if (track) {
        track.onended = () => {
          cleanup(true);
        };
      }

      await pushFrame();
      state._timer = setInterval(pushFrame, state._intervalMs);
      return { ok: true };
    } catch (exc) {
      const msg =
        exc?.name === "NotAllowedError"
          ? "Screen share permission denied."
          : String(exc?.message || exc);
      setError(msg);
      return { ok: false, error: msg };
    }
  }

  async function stopShare() {
    await cleanup(true);
    return { ok: true };
  }

  async function refreshStatus() {
    try {
      const r = await fetch("/api/voice/agent/vision/status");
      if (!r.ok) return;
      const data = await r.json();
      if (!state.active && data.active) {
        state.label = data.label || "";
        state.lastSentAt = data.age_ms != null ? Date.now() - data.age_ms : 0;
      }
    } catch (_) {}
  }

  window.addEventListener("beforeunload", () => {
    cleanup(false);
  });

  async function captureOnce() {
    if (!state.active) return null;
    return frameFromVideo(state._gameMode ? GAME_MAX_WIDTH : MAX_WIDTH);
  }

  window.mayaVisionCapture = {
    get active() {
      return state.active;
    },
    get label() {
      return state.label;
    },
    get lastSentAt() {
      return state.lastSentAt;
    },
    get error() {
      return state.error;
    },
    subscribe(fn) {
      state._listeners.add(fn);
      return () => state._listeners.delete(fn);
    },
    startShare,
    start(opts) {
      return startShare({ ...opts, gameMode: true });
    },
    stopShare,
    captureOnce,
    refreshStatus,
  };
})();
