/** AniSkip prefs + helpers for anime OP/ED skipping. */

const AUTO_OP_KEY = 'cinemaya:aniskip-auto-op'
const AUTO_ED_KEY = 'cinemaya:aniskip-auto-ed'

export type AniSkipType = 'op' | 'ed' | 'mixed-op' | 'mixed-ed' | 'recap' | string

export type AniSkipSegment = {
  skipId: string
  skipType: AniSkipType
  startTime: number
  endTime: number
  episodeLength?: number
}

export function readAutoSkipIntro(): boolean {
  try {
    return localStorage.getItem(AUTO_OP_KEY) !== '0'
  } catch {
    return true
  }
}

export function saveAutoSkipIntro(on: boolean) {
  try {
    localStorage.setItem(AUTO_OP_KEY, on ? '1' : '0')
  } catch {
    /* ignore */
  }
}

export function readAutoSkipOutro(): boolean {
  try {
    return localStorage.getItem(AUTO_ED_KEY) !== '0'
  } catch {
    return true
  }
}

export function saveAutoSkipOutro(on: boolean) {
  try {
    localStorage.setItem(AUTO_ED_KEY, on ? '1' : '0')
  } catch {
    /* ignore */
  }
}

export function isIntroSkipType(type: string): boolean {
  return type === 'op' || type === 'mixed-op' || type === 'recap'
}

export function isOutroSkipType(type: string): boolean {
  return type === 'ed' || type === 'mixed-ed'
}

export function skipButtonLabel(type: string): string {
  if (type === 'recap') return 'Skip recap'
  if (isOutroSkipType(type)) return 'Skip outro'
  return 'Skip intro'
}

/** Active segment at playback time (prefer shorter / later start). */
export function activeSkipAt(
  segments: AniSkipSegment[],
  time: number,
  pad = 0.35,
): AniSkipSegment | null {
  const hits = segments.filter(
    (s) => time >= s.startTime - pad && time < s.endTime - 0.4,
  )
  if (!hits.length) return null
  hits.sort(
    (a, b) =>
      a.endTime - a.startTime - (b.endTime - b.startTime) || b.startTime - a.startTime,
  )
  return hits[0] || null
}

export function shouldAutoSkip(
  segment: AniSkipSegment,
  autoIntro: boolean,
  autoOutro: boolean,
): boolean {
  if (isIntroSkipType(segment.skipType)) return autoIntro
  if (isOutroSkipType(segment.skipType)) return autoOutro
  return false
}
