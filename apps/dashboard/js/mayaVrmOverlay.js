/**
 * Standalone transparent VRM overlay for OBS/Streaming.
 * Supports dual-mode:
 * 1. BroadcastChannel (for zero-latency local relay when run in the same browser).
 * 2. Standalone HTTP SSE + Spectrum polling (for OBS Browser Source and sandboxed environments).
 */
import { MayaVrmEngine, resolveVrmUrl } from "/dashboard/js/mayaVrmEngine.js";
import { createVrmBus } from "/dashboard/js/mayaVrmBus.js";

const OVERLAY_KEY = "maya.vrm.overlay";

const canvas = document.getElementById("vo-canvas");
const loadingEl = document.getElementById("vo-loading");
const errorEl = document.getElementById("vo-error");
const subtitleContainer = document.getElementById("vo-subtitle-container");
const subtitleText = document.getElementById("vo-subtitle-text");
const bus = createVrmBus();

let engine = null;
let es = null;
let specTimer = null;
let subtitleClearTimer = null;
let lastBcLipTime = 0;
let lipIdlePolls = 0;

function applyLipFrame(frame) {
  if (!engine) return;
  const level = Number(frame?.level) || 0;
  const speaking = !!frame?.speaking || level > 0.002;
  engine.setAudioFrame({
    speaking,
    level,
    bands: Array.isArray(frame?.bands) ? frame.bands : [],
  });
  if (speaking) lipIdlePolls = 0;
}

function showError(msg) {
  if (msg) {
    errorEl.hidden = false;
    errorEl.textContent = msg;
  } else {
    errorEl.hidden = true;
    errorEl.textContent = "";
  }
}

async function loadSettings() {
  const r = await fetch("/api/voice/settings");
  if (!r.ok) throw new Error("Could not load settings");
  const data = await r.json();
  return data.settings?.vrm || {};
}

let subtitleTimeout = null;
let currentWords = [];
let displayCount = 0;
let isFinal = false;

function showSubtitle(text, final) {
  if (subtitleClearTimer) {
    clearTimeout(subtitleClearTimer);
    subtitleClearTimer = null;
  }
  
  if (final !== undefined) {
    isFinal = !!final;
  }
  
  const cleanTxt = (text || "").trim();
  if (!cleanTxt) {
    if (final) {
      isFinal = true;
      if (!subtitleTimeout && displayCount >= currentWords.length) {
        subtitleClearTimer = setTimeout(() => {
          if (subtitleText.querySelectorAll(".word:not(.faded)").length === 0) {
            subtitleContainer.classList.remove("visible");
            subtitleText.innerHTML = "";
            currentWords = [];
            displayCount = 0;
            isFinal = false;
          }
        }, 4500);
      }
    }
    return;
  }

  const incomingWords = cleanTxt.split(/\s+/);
  const shownPrefix = currentWords.slice(0, displayCount).join(" ");

  if (currentWords.length === 0) {
    currentWords = incomingWords;
    displayCount = 0;
    subtitleText.textContent = "";
    if (subtitleTimeout) {
      clearTimeout(subtitleTimeout);
      subtitleTimeout = null;
    }
  } else if (cleanTxt.startsWith(shownPrefix) && cleanTxt.length >= shownPrefix.length) {
    currentWords = incomingWords;
  } else if (cleanTxt.startsWith(currentWords.join(" "))) {
    currentWords = incomingWords;
  } else if (displayCount > 0) {
    currentWords = currentWords.concat(incomingWords);
  } else if (!cleanTxt.startsWith(shownPrefix)) {
    displayCount = 0;
    subtitleText.textContent = "";
    currentWords = incomingWords;
    if (subtitleTimeout) {
      clearTimeout(subtitleTimeout);
      subtitleTimeout = null;
    }
  } else {
    currentWords = incomingWords;
  }
  subtitleContainer.classList.add("visible");

  function revealNextWord() {
    if (displayCount < currentWords.length) {
      const word = currentWords[displayCount];
      displayCount++;
      
      const span = document.createElement("span");
      span.className = "word";
      span.textContent = word;
      subtitleText.appendChild(span);
      
      requestAnimationFrame(() => {
        span.classList.add("visible");
      });
      
      // Keep individual words on screen for 4 seconds, then fade out oldest first
      setTimeout(() => {
        span.classList.remove("visible");
        span.classList.add("faded");
        setTimeout(() => {
          span.remove();
        }, 500);
      }, 4000);
      
      // Calculate delay based on word length + a base delay to match human speech cadence:
      // ~65ms per character + 80ms word gap.
      const delay = (word.length * 65) + 80;
      subtitleTimeout = setTimeout(revealNextWord, delay);
    } else {
      subtitleTimeout = null;
      if (isFinal) {
        isFinal = false;
        subtitleClearTimer = setTimeout(() => {
          // If no active words are left in the container, hide it
          if (subtitleText.querySelectorAll(".word:not(.faded)").length === 0) {
            subtitleContainer.classList.remove("visible");
            subtitleText.innerHTML = "";
            currentWords = [];
            displayCount = 0;
          }
        }, 4500);
      }
    }
  }

  if (!subtitleTimeout) {
    revealNextWord();
  }
}

function startSpectrumPoll() {
  // Prefer BroadcastChannel lip when the dashboard tab is relaying (same browser).
  if (Date.now() - lastBcLipTime < 2000) return;
  if (specTimer) return;
  lipIdlePolls = 0;
  specTimer = setInterval(async () => {
    try {
      const r = await fetch("/api/voice/agent/spectrum");
      if (!r.ok) return;
      const frame = await r.json();
      const level = Number(frame.level) || 0;
      const speaking = !!frame.speaking || level > 0.002;
      applyLipFrame({ speaking, level, bands: frame.bands });
      if (speaking) {
        lipIdlePolls = 0;
        return;
      }
      lipIdlePolls += 1;
      if (lipIdlePolls >= 20) {
        stopSpectrumPoll();
      }
    } catch (_) {}
  }, 50);
}

function stopSpectrumPoll() {
  if (specTimer) {
    clearInterval(specTimer);
    specTimer = null;
  }
  lipIdlePolls = 0;
  engine?.setAudioFrame({ speaking: false, level: 0, bands: [] });
}

function handleAgentEvent(ev) {
  if (!ev || !engine) return;

  if (ev.type === "avatar_expression" && ev.mood) {
    if (ev.ease && String(ev.mood).toLowerCase() === "idle") engine.easeMoodToIdle();
    else engine.setMood(ev.mood);
  }
  if (ev.type === "avatar_animation" && ev.name) {
    engine.playAnimation(ev.name, { loop: !!ev.loop });
  }
  if (ev.type === "ai" && ev.text) {
    showSubtitle(ev.text, !!ev.final);
  }
  if (ev.type === "lip") {
    lastBcLipTime = Date.now();
    applyLipFrame(ev);
    if (Number(ev.level) > 0.002 || ev.speaking) startSpectrumPoll();
  }
  if (ev.type === "status") {
    const v = ev.value || "idle";
    if (v === "speaking") {
      startSpectrumPoll();
    }
  }
  if (ev.type === "audio_stop") {
    stopSpectrumPoll();
    applyLipFrame({ speaking: false, level: 0, bands: [] });
    engine?.lipSync?.reset();
  }
}

function connectSSE() {
  if (es) return;
  es = new EventSource("/api/voice/agent/events");
  es.onmessage = (e) => {
    try {
      const ev = JSON.parse(e.data);
      handleAgentEvent(ev);
    } catch (_) {}
  };
  es.onerror = () => {
    // SSE reconnects automatically
  };
}

async function boot() {
  try {
    const vrm = await loadSettings();
    engine = new MayaVrmEngine(canvas, {
      mouthGain: Number(vrm.mouth_gain ?? 6),
      mouthSmoothing: Number(vrm.mouth_smoothing ?? 0.5),
      lipSyncMode: vrm.lip_sync_mode === "amplitude" ? "amplitude" : "viseme",
      lookAtCamera: vrm.look_at_camera !== false,
      cameraDistance: Number(vrm.camera_distance ?? 1.8),
      idleEnabled: vrm.idle_enabled !== false,
      idleAnimation: vrm.idle_animation || "Idle.fbx",
      idleVariants: Array.isArray(vrm.idle_variants) ? vrm.idle_variants : [],
      idleVariantMinS: Number(vrm.idle_variant_min_s ?? 10),
      idleVariantMaxS: Number(vrm.idle_variant_max_s ?? 28),
    });
    engine.watchResize();
    engine.start();
    await engine.loadModel(resolveVrmUrl(vrm.model));
    loadingEl.hidden = true;
    loadingEl.style.display = "none";
    bus.post({ type: "popout-ready" }); // Let the dashboard know we're rendering
    
    // Connect to SSE for standalone overlay mode
    connectSSE();
  } catch (e) {
    loadingEl.textContent = "Failed to load";
    showError(String(e.message || e));
  }
}

bus.on((msg) => {
  if (!msg || !engine) return;
  if (msg.type === "lip") {
    lastBcLipTime = Date.now();
    applyLipFrame(msg);
  }
  if (msg.type === "subtitle") {
    showSubtitle(msg.text, !!msg.final);
  }
  if (msg.type === "animation" && msg.name) {
    engine.playAnimation(msg.name, { loop: !!msg.loop });
  }
  if (msg.type === "expression" && msg.mood) {
    if (msg.ease && String(msg.mood).toLowerCase() === "idle") engine.easeMoodToIdle();
    else engine.setMood(msg.mood);
  }
  if (msg.type === "settings" && msg.vrm) {
    const v = msg.vrm;
    if (v.mouth_gain != null) engine.setMouthGain(v.mouth_gain);
    if (v.mouth_smoothing != null) engine.setMouthSmoothing(v.mouth_smoothing);
    if (v.lip_sync_mode != null) engine.setLipSyncMode(v.lip_sync_mode);
    if (v.idle_animation != null) engine.setIdleAnimation(v.idle_animation);
    if (v.idle_variants != null) engine.setIdleVariants(v.idle_variants);
    if (v.idle_variant_min_s != null || v.idle_variant_max_s != null) {
      engine.setIdleVariantInterval(v.idle_variant_min_s, v.idle_variant_max_s);
    }
    if (v.model != null) engine.loadModel(resolveVrmUrl(v.model));
  }
});

window.addEventListener("beforeunload", () => {
  bus.post({ type: "popout-close" });
  es?.close();
  engine?.dispose();
});

localStorage.setItem(OVERLAY_KEY, "1");
boot();
