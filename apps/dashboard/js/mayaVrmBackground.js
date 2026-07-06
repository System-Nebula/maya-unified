/** VRM viewer stage backgrounds — CSS presets or uploaded image. */

export const VRM_BACKGROUND_PRESETS = {
  default: {
    label: "Studio dark",
    css: "radial-gradient(ellipse at 50% 20%, #1a2030 0%, #0d0d10 70%)",
  },
  soft: {
    label: "Soft grey",
    css: "radial-gradient(ellipse at 50% 30%, #2a2a38 0%, #121218 75%)",
  },
  blue: {
    label: "Cool blue",
    css: "radial-gradient(ellipse at 50% 15%, #1e3a5f 0%, #0a0e18 70%)",
  },
  sunset: {
    label: "Sunset",
    css: "radial-gradient(ellipse at 50% 80%, #4a2030 0%, #1a1018 60%, #0a0a0c 100%)",
  },
  neon: {
    label: "Neon purple",
    css: "radial-gradient(ellipse at 50% 20%, #1a1038 0%, #0d0818 70%)",
  },
  mint: {
    label: "Mint",
    css: "radial-gradient(ellipse at 50% 25%, #1a3030 0%, #0d1210 70%)",
  },
  transparent: {
    label: "Transparent",
    css: "transparent",
  },
};

export const DEFAULT_VRM_BACKGROUND = "default";

export function resolveVrmBackgroundUrl(name) {
  const raw = String(name || "").trim();
  if (!raw) return "";
  const base = raw.replace(/^.*[/\\]/, "");
  return `/api/voice/agent/vrm/background/file?name=${encodeURIComponent(base)}`;
}

export function applyVrmBackground(stageEl, { preset, image } = {}) {
  if (!stageEl) return;
  const p = String(preset || DEFAULT_VRM_BACKGROUND).toLowerCase();
  if (p === "custom" && image) {
    const url = resolveVrmBackgroundUrl(image);
    stageEl.style.background = `#0d0d10 url("${url}") center / cover no-repeat`;
    stageEl.dataset.vrmBg = "custom";
    return;
  }
  const def = VRM_BACKGROUND_PRESETS[p] || VRM_BACKGROUND_PRESETS.default;
  stageEl.style.background = def.css;
  stageEl.dataset.vrmBg = p in VRM_BACKGROUND_PRESETS ? p : DEFAULT_VRM_BACKGROUND;
}

export function applyVrmBackgroundAll(rootEl, config) {
  if (!rootEl) return;
  rootEl.querySelectorAll(".md-vrm-stage, .md-vrm-immersive-stage").forEach((el) => {
    applyVrmBackground(el, config);
  });
}
