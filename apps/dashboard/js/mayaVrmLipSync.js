/**
 * VRM lip-sync — amplitude + spectrum-driven viseme mixing for VRM0/VRM1 mouth presets.
 * Mirrors the VTube Studio mouth loop (gain + smoothing) but drives standard
 * VRM expressions: A/aa, I/ih, U/ou, E/ee, O/oh.
 *
 * Future: swap `pushPhonemes()` for Rhubarb / wLipSync / server-side viseme stream.
 */

/** @typedef {'a'|'i'|'u'|'e'|'o'} VisemeId */

const VISEME_ORDER = /** @type {const} */ (["a", "i", "u", "e", "o"]);

/** Canonical viseme → expression name candidates (VRM0 preset + common aliases). */
const VISEME_ALIASES = {
  a: ["aa", "a", "A", "vrc.v_aa", "mouth_a", "MouthA", "mouth_open"],
  i: ["ih", "i", "I", "vrc.v_ih", "mouth_i", "MouthI"],
  u: ["ou", "u", "U", "vrc.v_ou", "mouth_u", "MouthU"],
  e: ["ee", "e", "E", "vrc.v_ee", "mouth_e", "MouthE"],
  o: ["oh", "o", "O", "vrc.v_oh", "mouth_o", "MouthO"],
};

/**
 * @param {import('@pixiv/three-vrm').VRMExpressionManager | null | undefined} em
 * @returns {Record<VisemeId, string>}
 */
export function discoverMouthExpressions(em) {
  /** @type {Record<VisemeId, string>} */
  const found = {};
  if (!em) return found;

  const available = new Set(listExpressionNames(em));

  for (const id of VISEME_ORDER) {
    for (const candidate of VISEME_ALIASES[id]) {
      if (available.has(candidate)) {
        found[id] = candidate;
        break;
      }
      if (typeof em.getExpression === "function") {
        try {
          if (em.getExpression(candidate) != null) {
            found[id] = candidate;
            break;
          }
        } catch (_) {
          /* ignore */
        }
      }
    }
  }

  return found;
}

/**
 * @param {import('@pixiv/three-vrm').VRMExpressionManager} em
 * @returns {string[]}
 */
function listExpressionNames(em) {
  const names = [];
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
 * Map log-spaced spectrum bands to vowel weights, scaled by jaw openness.
 * @param {{ f?: number, v?: number }[]} bands
 * @param {number} jaw 0..1
 * @returns {Record<VisemeId, number>}
 */
export function visemesFromSpectrum(bands, jaw) {
  /** @type {Record<VisemeId, number>} */
  const out = { a: 0, i: 0, u: 0, e: 0, o: 0 };
  const open = Math.min(1, Math.max(0, jaw));
  if (open < 0.02 || !bands?.length) {
    return out;
  }

  let low = 0;
  let mid = 0;
  let high = 0;
  let total = 0;

  for (const band of bands) {
    const f = Number(band.f) || 0;
    const v = Math.max(0, Number(band.v) || 0);
    total += v;
    if (f < 450) low += v;
    else if (f < 1800) mid += v;
    else high += v;
  }

  const denom = total || 1;
  const ln = low / denom;
  const mn = mid / denom;
  const hn = high / denom;

  out.o = open * Math.min(1, ln * 1.35 + mn * 0.15);
  out.u = open * Math.min(1, ln * 0.95);
  out.a = open * Math.min(1, mn * 1.1 + ln * 0.25);
  out.e = open * Math.min(1, mn * 0.55 + hn * 0.65);
  out.i = open * Math.min(1, hn * 1.2 + mn * 0.2);

  return normalizeVisemes(out);
}

/**
 * @param {Record<VisemeId, number>} vis
 * @returns {Record<VisemeId, number>}
 */
function normalizeVisemes(vis) {
  const max = Math.max(...VISEME_ORDER.map((k) => vis[k] || 0), 0.001);
  if (max <= 1) return vis;
  /** @type {Record<VisemeId, number>} */
  const out = {};
  for (const k of VISEME_ORDER) out[k] = (vis[k] || 0) / max;
  return out;
}

export class VrmLipSync {
  /**
   * @param {object} [opts]
   * @param {number} [opts.gain]
   * @param {number} [opts.smoothing] 0 = snappy, 0.95 = very smooth
   * @param {'amplitude'|'viseme'} [opts.mode]
   */
  constructor(opts = {}) {
    this.gain = Number(opts.gain ?? 6);
    this.smoothing = Math.min(0.95, Math.max(0, Number(opts.smoothing ?? 0.5)));
    this.mode = opts.mode === "amplitude" ? "amplitude" : "viseme";
    this._em = null;
    /** @type {Record<VisemeId, string>} */
    this._keys = {};
    /** @type {Record<VisemeId, number>} */
    this._current = { a: 0, i: 0, u: 0, e: 0, o: 0 };
    /** @type {Record<VisemeId, number>} */
    this._target = { a: 0, i: 0, u: 0, e: 0, o: 0 };
    this._speaking = false;
    this._rawLevel = 0;
    /** @type {{ f?: number, v?: number }[]} */
    this._bands = [];
    this._lastApplied = { a: -1, i: -1, u: -1, e: -1, o: -1 };
    this._minDelta = 0.012;
  }

  /**
   * @param {import('@pixiv/three-vrm').VRM} vrm
   */
  bind(vrm) {
    this._em = vrm?.expressionManager ?? null;
    this._keys = discoverMouthExpressions(this._em);
    this.reset();
    return {
      keys: { ...this._keys },
      mode: this.mode,
      ready: Object.keys(this._keys).length > 0,
    };
  }

  setGain(v) {
    this.gain = Math.max(0.1, Number(v) || 6);
  }

  setSmoothing(v) {
    this.smoothing = Math.min(0.95, Math.max(0, Number(v) || 0.5));
  }

  setMode(mode) {
    this.mode = mode === "amplitude" ? "amplitude" : "viseme";
  }

  /**
   * @param {{ speaking?: boolean, level?: number, bands?: { f?: number, v?: number }[] }} frame
   */
  pushFrame(frame = {}) {
    this._rawLevel = Math.max(0, Number(frame.level) || 0);
    this._bands = Array.isArray(frame.bands) ? frame.bands : [];
    this._speaking = this._rawLevel > 0.002 || !!frame.speaking;

    if (!this._speaking) {
      return;
    }

    const jaw = Math.min(1, this._rawLevel * this.gain);

    if (this.mode === "amplitude") {
      this._target.a = jaw;
      this._target.i = 0;
      this._target.u = 0;
      this._target.e = 0;
      this._target.o = 0;
      return;
    }

    const vis = visemesFromSpectrum(this._bands, jaw);
    for (const id of VISEME_ORDER) {
      this._target[id] = this._keys[id] ? vis[id] : 0;
    }

    // If model only has jaw (A) but not vowel splits, fall back to amplitude on A.
    if (!this._keys.i && !this._keys.u && !this._keys.e && !this._keys.o && this._keys.a) {
      this._target.a = jaw;
    }
  }

  /**
   * @param {number} delta seconds since last frame
   */
  update(delta) {
    const alpha = 1 - this.smoothing;
    const step = Math.min(1, alpha * 0.65 + Math.max(0, delta) * 14);

    for (const id of VISEME_ORDER) {
      const tgt = this._speaking ? (this._target[id] ?? 0) : 0;
      let cur = this._current[id] ?? 0;
      cur += (tgt - cur) * step;
      if (!this._speaking && cur < 0.01) cur = 0;
      this._current[id] = cur;
      this._apply(id, cur);
    }
  }

  reset() {
    for (const id of VISEME_ORDER) {
      this._target[id] = 0;
      this._lastApplied[id] = -1;
    }
    this._speaking = false;
    this._rawLevel = 0;
    this._bands = [];
    // Mouth values decay via update(); do not snap expressions to zero here.
  }

  /**
   * Optional hook for future phoneme-driven sync (Rhubarb, wLipSync, server visemes).
   * @param {{ viseme: VisemeId, weight: number }[]} phonemes
   * @param {number} [jaw=1]
   */
  pushPhonemes(phonemes, jaw = 1) {
    if (!this._speaking) return;
    const open = Math.min(1, Math.max(0, jaw));
    for (const id of VISEME_ORDER) this._target[id] = 0;
    for (const p of phonemes || []) {
      const id = p?.viseme;
      if (id && this._keys[id]) {
        this._target[id] = Math.min(1, Math.max(0, Number(p.weight) || 0) * open);
      }
    }
  }

  /** @param {VisemeId} id @param {number} value */
  _apply(id, value) {
    const name = this._keys[id];
    if (!name || !this._em) return;
    const v = Math.min(1, Math.max(0, value));
    if (Math.abs(v - (this._lastApplied[id] ?? -1)) < this._minDelta) return;
    this._lastApplied[id] = v;
    try {
      this._em.setValue(name, v);
    } catch (_) {
      /* expression may be missing on this VRM build */
    }
  }
}
