/**
 * Cute programmatic VRM face moods — layered under lip-sync (mouth slots protected).
 */

export const AVATAR_MOODS = /** @type {const} */ ([
  "idle",
  "happy",
  "excited",
  "surprised",
  "angry",
  "frustrated",
]);

/** @typedef {(typeof AVATAR_MOODS)[number]} AvatarMood */

/** Canonical mood slots → VRM expression name candidates. */
const SLOT_ALIASES = {
  happy: ["happy", "Happy", "joy", "Joy", "vrc.v_happy", "HAPPY", "Smile"],
  angry: ["angry", "Angry", "vrc.v_angry", "ANGRY", "Mad"],
  sad: ["sad", "Sad", "vrc.v_sad", "SAD", "Sorrow"],
  surprised: ["surprised", "Surprised", "surprise", "vrc.v_surprised", "SURPRISED"],
  relaxed: ["relaxed", "Relaxed", "neutral", "Neutral", "vrc.v_relaxed", "NEUTRAL", "default"],
};

/** Subtle, cute blend weights — never full 1.0. */
const CUTE_PRESETS = /** @type {Record<AvatarMood, Record<string, number>>} */ ({
  idle: { relaxed: 0.28 },
  happy: { happy: 0.52, relaxed: 0.12 },
  excited: { happy: 0.42, surprised: 0.32, relaxed: 0.08 },
  surprised: { surprised: 0.48, happy: 0.08 },
  angry: { angry: 0.38, sad: 0.1 },
  frustrated: { angry: 0.22, sad: 0.38, relaxed: 0.05 },
});

const MOUTH_GUARD = new Set([
  "aa", "a", "A", "ih", "i", "I", "ou", "u", "U", "ee", "e", "E", "oh", "o", "O",
  "vrc.v_aa", "vrc.v_ih", "vrc.v_ou", "vrc.v_ee", "vrc.v_oh",
  "mouth_a", "mouth_i", "mouth_u", "mouth_e", "mouth_o",
  "MouthA", "MouthI", "MouthU", "MouthE", "MouthO", "mouth_open",
]);

/**
 * @param {import('@pixiv/three-vrm').VRMExpressionManager | null | undefined} em
 * @returns {string[]}
 */
export function listExpressionNames(em) {
  const names = [];
  if (!em) return names;
  if (Array.isArray(em.expressions)) {
    for (const expr of em.expressions) {
      const n = expr?.expressionName ?? expr?.name;
      if (n) names.push(n);
    }
  }
  if (em.expressionMap instanceof Map) {
    for (const key of em.expressionMap.keys()) names.push(key);
  } else if (em.expressionMap && typeof em.expressionMap === "object") {
    names.push(...Object.keys(em.expressionMap));
  }
  return [...new Set(names)];
}

/**
 * @param {import('@pixiv/three-vrm').VRMExpressionManager} em
 * @param {string[]} aliases
 * @returns {string | null}
 */
function resolveSlot(em, aliases) {
  const available = new Set(listExpressionNames(em));
  for (const candidate of aliases) {
    if (available.has(candidate)) return candidate;
    if (typeof em.getExpression === "function") {
      try {
        if (em.getExpression(candidate) != null) return candidate;
      } catch (_) {
        /* ignore */
      }
    }
  }
  return null;
}

export class VrmExpressionController {
  constructor() {
    /** @type {import('@pixiv/three-vrm').VRMExpressionManager | null} */
    this._em = null;
    /** @type {Record<string, string>} canonical slot → expression name */
    this._slots = {};
    /** @type {Set<string>} */
    this._managed = new Set();
    /** @type {Record<string, number>} */
    this._current = {};
    /** @type {Record<string, number>} */
    this._target = {};
    this._mood = /** @type {AvatarMood} */ ("idle");
    this._blendSpeed = 5.5;
    this._returnBlendSpeed = 2.4;
    this._returnBlend = false;
  }

  /**
   * @param {import('@pixiv/three-vrm').VRM} vrm
   * @param {{ extraProtected?: string[] }} [opts]
   */
  bind(vrm, opts = {}) {
    this._em = vrm?.expressionManager ?? null;
    this._slots = {};
    this._managed = new Set();
    this._current = {};
    this._target = {};
    if (!this._em) return { ready: false, slots: {} };

    const extra = new Set(opts.extraProtected || []);
    for (const [canonical, aliases] of Object.entries(SLOT_ALIASES)) {
      const resolved = resolveSlot(this._em, aliases);
      if (resolved && !MOUTH_GUARD.has(resolved) && !extra.has(resolved)) {
        this._slots[canonical] = resolved;
        this._managed.add(resolved);
      }
    }
    this.setMood("idle", { immediate: true });
    return { ready: this._managed.size > 0, slots: { ...this._slots }, mood: this._mood };
  }

  /** @param {string} raw */
  normalizeMood(raw) {
    const m = String(raw || "").trim().toLowerCase();
    if (AVATAR_MOODS.includes(/** @type {AvatarMood} */ (m))) return /** @type {AvatarMood} */ (m);
    if (m === "neutral" || m === "calm" || m === "default") return "idle";
    if (m === "joy" || m === "smile" || m === "glad") return "happy";
    if (m === "mad" || m === "upset" || m === "annoyed") return "angry";
    if (m === "shock" || m === "shocked" || m === "wow") return "surprised";
    if (m === "sad" || m === "upset" || m === "annoyed") return "frustrated";
    return "idle";
  }

  /**
   * @param {string} mood
   * @param {{ immediate?: boolean }} [opts]
   */
  setMood(mood, opts = {}) {
    const normalized = this.normalizeMood(mood);
    this._mood = normalized;
    if (opts.return) this._returnBlend = true;
    const preset = CUTE_PRESETS[normalized] || CUTE_PRESETS.idle;
    /** @type {Record<string, number>} */
    const next = {};
    for (const [canonical, weight] of Object.entries(preset)) {
      const name = this._slots[canonical];
      if (name) next[name] = Math.min(1, Math.max(0, weight));
    }
    for (const name of this._managed) {
      this._target[name] = next[name] ?? 0;
      if (opts.immediate) {
        this._current[name] = this._target[name];
        this._apply(name, this._current[name]);
      }
    }
  }

  easeToIdle() {
    if (this._mood === "idle" && !this._returnBlend) return;
    this.setMood("idle", { return: true });
  }

  getMood() {
    return this._mood;
  }

  /** @param {number} delta */
  update(delta) {
    if (!this._em || !this._managed.size) return;
    const speed = this._returnBlend ? this._returnBlendSpeed : this._blendSpeed;
    const step = Math.min(1, Math.max(0, delta) * speed);
    let settled = true;
    for (const name of this._managed) {
      const tgt = this._target[name] ?? 0;
      let cur = this._current[name] ?? 0;
      cur += (tgt - cur) * step;
      if (Math.abs(tgt - cur) > 0.02) settled = false;
      if (Math.abs(tgt) < 0.01 && cur < 0.01) cur = 0;
      this._current[name] = cur;
      this._apply(name, cur);
    }
    if (this._returnBlend && settled && this._mood === "idle") {
      this._returnBlend = false;
    }
  }

  reset() {
    this.setMood("idle", { immediate: true });
  }

  /** @param {string} name @param {number} value */
  _apply(name, value) {
    if (!this._em) return;
    try {
      this._em.setValue(name, Math.min(1, Math.max(0, value)));
    } catch (_) {
      /* missing on this VRM */
    }
  }
}
