/**
 * Standalone draggable VRM pop-out window.
 * Lip-sync frames are relayed from the main dashboard via BroadcastChannel.
 */
import { MayaVrmEngine, resolveVrmUrl } from "/dashboard/js/mayaVrmEngine.js";
import { createVrmBus } from "/dashboard/js/mayaVrmBus.js";

const POPOUT_KEY = "maya.vrm.popout";

const canvas = document.getElementById("vp-canvas");
const loadingEl = document.getElementById("vp-loading");
const errorEl = document.getElementById("vp-error");
const dragBar = document.getElementById("vp-drag");
const bus = createVrmBus();

let engine = null;

function showError(msg) {
  errorEl.hidden = !msg;
  errorEl.textContent = msg || "";
}

async function loadSettings() {
  const r = await fetch("/api/voice/settings");
  if (!r.ok) throw new Error("Could not load settings");
  const data = await r.json();
  return data.settings?.vrm || {};
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
    });
    engine.watchResize();
    engine.start();
    await engine.loadModel(resolveVrmUrl(vrm.model));
    loadingEl.hidden = true;
    loadingEl.style.display = "none";
    bus.post({ type: "popout-ready" });
  } catch (e) {
    loadingEl.textContent = "Failed to load";
    showError(String(e.message || e));
  }
}

bus.on((msg) => {
  if (!msg || !engine) return;
  if (msg.type === "lip") {
    engine.setAudioFrame({
      speaking: !!msg.speaking,
      level: Number(msg.level) || 0,
      bands: Array.isArray(msg.bands) ? msg.bands : [],
    });
  }
  if (msg.type === "animation" && msg.name) {
    engine.playAnimation(msg.name, { loop: !!msg.loop });
  }
  if (msg.type === "settings" && msg.vrm) {
    const v = msg.vrm;
    if (v.mouth_gain != null) engine.setMouthGain(v.mouth_gain);
    if (v.mouth_smoothing != null) engine.setMouthSmoothing(v.mouth_smoothing);
    if (v.lip_sync_mode != null) engine.setLipSyncMode(v.lip_sync_mode);
    if (v.idle_animation != null) engine.setIdleAnimation(v.idle_animation);
    if (v.model != null) engine.loadModel(resolveVrmUrl(v.model));
  }
});

// Window drag (move popup by title bar)
let drag = null;
dragBar.addEventListener("pointerdown", (e) => {
  if (e.target.closest("button")) return;
  drag = { x: e.screenX, y: e.screenY, wx: window.screenX, wy: window.screenY };
  dragBar.setPointerCapture(e.pointerId);
});
dragBar.addEventListener("pointermove", (e) => {
  if (!drag) return;
  const dx = e.screenX - drag.x;
  const dy = e.screenY - drag.y;
  window.moveTo(drag.wx + dx, drag.wy + dy);
});
dragBar.addEventListener("pointerup", () => {
  drag = null;
});

document.getElementById("vp-close").addEventListener("click", () => {
  bus.post({ type: "popout-close" });
  window.close();
});

document.getElementById("vp-always").addEventListener("click", async () => {
  try {
    await document.documentElement.requestFullscreen?.();
  } catch (_) {
    /* optional */
  }
});

window.addEventListener("beforeunload", () => {
  bus.post({ type: "popout-close" });
  engine?.dispose();
});

localStorage.setItem(POPOUT_KEY, "1");
boot();
