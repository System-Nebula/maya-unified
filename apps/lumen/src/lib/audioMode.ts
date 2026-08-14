import type { LabStream } from '../api/lab'
import { formatPlayableQuality } from './streamQuality'

export type AudioMode = 'sub' | 'dub' | 'any'

const KEY = 'cinemaya:audio-mode'

const PREFERRED_SOURCES = [
  'link',
  'lul',
  'nebula',
  'meridian',
  'tiki',
  'vidy',
  'onion',
  'vixsrc',
  'cowflix',
]

export function readAudioMode(): AudioMode {
  try {
    const v = localStorage.getItem(KEY)
    if (v === 'sub' || v === 'dub' || v === 'any') return v
  } catch {
    /* ignore */
  }
  return 'any'
}

export function saveAudioMode(mode: AudioMode) {
  try {
    localStorage.setItem(KEY, mode)
  } catch {
    /* ignore */
  }
}

/** Infer sub/dub from provider + embed labels (HiAnime HD-1 (Dub), etc.). */
export function streamAudioKind(stream: LabStream): AudioMode | 'unknown' {
  // Prefer explicit embed id/name from scrapers (Anisurge uses id "sub"|"dub").
  const embedId = String(stream.embedId || '')
    .trim()
    .toLowerCase()
  const embedName = String(stream.embedName || '')
    .trim()
    .toLowerCase()
  if (embedId === 'dub' || embedId === 'dubbed' || /^(dub|dubbed)$/i.test(embedName)) return 'dub'
  if (embedId === 'sub' || embedId === 'subbed' || /^(sub|subbed)$/i.test(embedName)) return 'sub'

  // Do not scan sourceId — ids like anivexa-anikoto are unrelated noise.
  const label = `${stream.sourceName || ''} ${stream.embedName || ''}`
  const lower = label.toLowerCase()
  const hasDub = /\bdub(bed)?\b/.test(lower) || /[-_]dub\b/.test(lower) || /\ben-?dub\b/.test(lower)
  const hasSub =
    /\bsub(bed)?\b/.test(lower) ||
    /[-_]sub\b/.test(lower) ||
    /\bsubtitulado\b/.test(lower) ||
    /\bjapanese\b/.test(lower) ||
    /\braw\b/.test(lower)
  // Explicit dub wins over generic "subtitles" wording in labels
  if (hasDub && !hasSub) return 'dub'
  if (hasSub && !hasDub) return 'sub'
  if (hasDub && hasSub) {
    // e.g. "HD-1 (Dub)" vs mixed — prefer the last strong signal
    if (/dub\)?\s*$/i.test(lower) || /\(dub\)/i.test(lower)) return 'dub'
    if (/sub\)?\s*$/i.test(lower) || /\(sub\)/i.test(lower)) return 'sub'
    return 'unknown'
  }
  return 'unknown'
}

/**
 * For non-English originals (anime), unlabeled streams are almost always
 * original-language audio (= Sub). Dub only when explicitly labeled.
 */
export function effectiveAudioKind(
  stream: LabStream,
  originalLanguage?: string | null,
): AudioMode | 'unknown' {
  const kind = streamAudioKind(stream)
  if (kind !== 'unknown') return kind
  if (isNonEnglishOriginal(originalLanguage)) return 'sub'
  return 'unknown'
}

export function streamsOfferSubDub(
  streams: LabStream[],
  originalLanguage?: string | null,
): boolean {
  let sub = false
  let dub = false
  for (const s of streams) {
    const kind = effectiveAudioKind(s, originalLanguage)
    if (kind === 'sub') sub = true
    if (kind === 'dub') dub = true
  }
  return sub && dub
}

/** Sub/Dub toggle is for non-English originals (anime, foreign films). */
export function isNonEnglishOriginal(originalLanguage?: string | null): boolean {
  if (!originalLanguage) return false
  const code = originalLanguage.trim().toLowerCase().split(/[-_]/)[0]
  return Boolean(code) && code !== 'en'
}

/** Show the AUDIO Sub/Dub control only for foreign-language titles. */
export function shouldShowAudioModeToggle(originalLanguage?: string | null): boolean {
  return isNonEnglishOriginal(originalLanguage)
}

/**
 * Honor explicit Sub/Dub preference unless the title is known English
 * (where the toggle does not apply). Unknown language still honors the
 * preference so anime Dub is not lost while TMDB loads.
 */
export function resolveAudioMode(
  mode: AudioMode,
  originalLanguage?: string | null,
): AudioMode {
  if (mode === 'any') return 'any'
  if (originalLanguage && !isNonEnglishOriginal(originalLanguage)) return 'any'
  return mode
}

/** Next stream index matching audio preference, starting after `fromIndex`. */
export function nextMatchingStreamIndex(
  streams: LabStream[],
  fromIndex: number,
  mode: AudioMode,
  originalLanguage?: string | null,
): number {
  if (!streams.length) return -1
  const effectiveMode = resolveAudioMode(mode, originalLanguage)
  for (let i = fromIndex + 1; i < streams.length; i++) {
    if (effectiveMode === 'any' || effectiveAudioKind(streams[i], originalLanguage) === effectiveMode) {
      return i
    }
  }
  return -1
}

/**
 * Failover pick: prefer another source at the same/higher quality before
 * dropping (e.g. Link 1080 → other 1080, not straight to Pseudo 720).
 */
export function nextFailoverStreamIndex(
  streams: LabStream[],
  fromIndex: number,
  mode: AudioMode,
  originalLanguage?: string | null,
): number {
  if (!streams.length) return -1
  const effectiveMode = resolveAudioMode(mode, originalLanguage)
  const currentH = fromIndex >= 0 ? streamQualityHeight(streams[fromIndex]!) : 0
  const rest: number[] = []
  for (let i = 0; i < streams.length; i++) {
    if (i === fromIndex) continue
    if (
      effectiveMode !== 'any' &&
      effectiveAudioKind(streams[i]!, originalLanguage) !== effectiveMode
    ) {
      continue
    }
    rest.push(i)
  }
  if (!rest.length) return -1
  const ge = rest.filter((i) => streamQualityHeight(streams[i]!) >= currentH && currentH > 0)
  if (ge.length) return pickBestQualityIndex(streams, ge)
  return pickBestQualityIndex(streams, rest)
}

function streamQualityHeight(stream: LabStream): number {
  const raw = String(stream.playable?.quality || '')
    .trim()
    .toLowerCase()
  if (!raw || raw === 'unknown') return 0
  if (raw === '4k' || raw === 'uhd') return 2160
  const m = raw.match(/^(\d{3,4})p?$/)
  return m ? Number(m[1]) || 0 : 0
}

/** Among candidate indices, pick highest quality (then lowest index). */
function pickBestQualityIndex(streams: LabStream[], candidates: number[]): number {
  if (!candidates.length) return -1
  let best = candidates[0]!
  let bestH = streamQualityHeight(streams[best]!)
  for (let i = 1; i < candidates.length; i++) {
    const idx = candidates[i]!
    const h = streamQualityHeight(streams[idx]!)
    if (h > bestH || (h === bestH && idx < best)) {
      best = idx
      bestH = h
    }
  }
  return best
}

export function pickStreamIndex(
  streams: LabStream[],
  mode: AudioMode,
  originalLanguage?: string | null,
): number {
  if (!streams.length) return -1
  const effectiveMode = resolveAudioMode(mode, originalLanguage)
  const pool =
    effectiveMode === 'any'
      ? streams.map((_, i) => i)
      : streams
          .map((s, i) => (effectiveAudioKind(s, originalLanguage) === effectiveMode ? i : -1))
          .filter((i) => i >= 0)

  // Do not silently fall back to the wrong audio when Sub/Dub is intentional.
  if (effectiveMode !== 'any' && !pool.length) return -1

  const candidates = pool.length ? pool : streams.map((_, i) => i)
  for (const id of PREFERRED_SOURCES) {
    const hits = candidates.filter((i) => streams[i]?.sourceId === id)
    if (hits.length) return pickBestQualityIndex(streams, hits)
  }
  return pickBestQualityIndex(streams, candidates)
}

export function filterStreamsByAudio(
  streams: LabStream[],
  mode: AudioMode,
  originalLanguage?: string | null,
): LabStream[] {
  const effectiveMode = resolveAudioMode(mode, originalLanguage)
  if (effectiveMode === 'any') return streams
  const filtered = streams.filter((s) => effectiveAudioKind(s, originalLanguage) === effectiveMode)
  return filtered
}

function cleanSourceName(name: string): string {
  return name
    .replace(/🌊/g, '')
    .replace(/[\u{1F300}-\u{1FAFF}]/gu, '')
    .replace(/\s+/g, ' ')
    .trim()
}

/** One clean menu label — never "Dub · Anokoto · Dub". */
export function formatStreamLabel(
  stream: LabStream,
  originalLanguage?: string | null,
): string {
  const source = cleanSourceName(stream.sourceName || stream.sourceId || 'Source')
  const embed = String(stream.embedName || '').trim()
  const kind = effectiveAudioKind(stream, originalLanguage)
  const quality = formatPlayableQuality(stream.playable?.quality)

  if (/^(sub|dub|subbed|dubbed)$/i.test(embed)) {
    const base = `${source} · ${/^dub/i.test(embed) ? 'Dub' : 'Sub'}`
    return quality ? `${base} · ${quality}` : base
  }

  const embedHasAudio = /\b(sub|dub)(bed)?\b/i.test(embed)
  const parts: string[] = []
  if ((kind === 'sub' || kind === 'dub') && !embedHasAudio) {
    parts.push(kind === 'sub' ? 'Sub' : 'Dub')
  }
  parts.push(source)
  if (embed) parts.push(embed)
  if (quality) parts.push(quality)
  return parts.join(' · ')
}
