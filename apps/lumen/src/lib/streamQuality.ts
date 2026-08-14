const ALWAYS_HD_KEY = 'cinemaya:always-hd'
const QUALITY_PREF_KEY = 'cinemaya:quality-pref'

export type QualityOption = {
  id: string
  /** -1 = Auto */
  level: number
  label: string
  bitrateLabel: string | null
  height: number
}

export function readAlwaysHd(): boolean {
  try {
    return localStorage.getItem(ALWAYS_HD_KEY) === '1'
  } catch {
    return false
  }
}

export function saveAlwaysHd(on: boolean) {
  try {
    localStorage.setItem(ALWAYS_HD_KEY, on ? '1' : '0')
  } catch {
    /* ignore */
  }
}

/** 'auto' or a height like 1080 */
export function readQualityPref(): string {
  try {
    return localStorage.getItem(QUALITY_PREF_KEY) || 'auto'
  } catch {
    return 'auto'
  }
}

export function saveQualityPref(pref: string) {
  try {
    localStorage.setItem(QUALITY_PREF_KEY, pref)
  } catch {
    /* ignore */
  }
}

export function formatHeightLabel(height: number): string {
  if (height >= 2160) return '2160p'
  if (height >= 1440) return '1440p'
  if (height >= 1080) return '1080p'
  if (height >= 720) return '720p'
  if (height >= 480) return '480p'
  if (height >= 360) return '360p'
  if (height >= 240) return '240p'
  return height > 0 ? `${height}p` : 'SD'
}

/** Normalize lab `playable.quality` ("1080", "4k", "720p") for source menus. */
export function formatPlayableQuality(quality?: string | null): string | null {
  if (quality == null) return null
  const raw = String(quality).trim()
  if (!raw || /^unknown$/i.test(raw)) return null
  const lower = raw.toLowerCase()
  if (lower === '4k' || lower === 'uhd') return '2160p'
  const m = lower.match(/^(\d{3,4})p?$/)
  if (m) {
    const height = Number(m[1])
    return height > 0 ? formatHeightLabel(height) : null
  }
  return raw
}

export function formatBitrate(bps: number | undefined): string | null {
  if (!bps || bps < 1) return null
  const mbps = bps / 1_000_000
  if (mbps >= 10) return `${mbps.toFixed(0)} Mbps`
  if (mbps >= 1) return `${mbps.toFixed(1)} Mbps`
  const kbps = bps / 1000
  return `${Math.max(1, Math.round(kbps))} Kbps`
}

export function levelsToQualityOptions(
  levels: Array<{ height?: number; width?: number; bitrate?: number; name?: string }>,
): QualityOption[] {
  const mapped = levels.map((level, index) => {
    const height = Number(level.height) || guessHeightFromWidth(level.width) || 0
    return {
      id: `level-${index}`,
      level: index,
      label: formatHeightLabel(height) || level.name || `Level ${index + 1}`,
      bitrateLabel: formatBitrate(level.bitrate),
      height,
    }
  })
  // Highest first in the menu (1080 → 360)
  return [...mapped].sort((a, b) => b.height - a.height || b.level - a.level)
}

function guessHeightFromWidth(width?: number): number {
  const w = Number(width) || 0
  if (w >= 3840) return 2160
  if (w >= 2560) return 1440
  if (w >= 1920) return 1080
  if (w >= 1280) return 720
  if (w >= 854) return 480
  if (w >= 640) return 360
  return 0
}

export function pickAlwaysHdLevel(options: QualityOption[]): number | null {
  const hd = options.filter((o) => o.height >= 720)
  if (hd.length) return hd[0]!.level
  return options[0]?.level ?? null
}

export function resolveInitialLevel(
  options: QualityOption[],
  pref: string,
  _alwaysHd: boolean,
): number {
  if (pref !== 'auto') {
    const height = Number(pref)
    const hit = options.find((o) => o.height === height)
    if (hit) return hit.level
  }
  return -1
}
