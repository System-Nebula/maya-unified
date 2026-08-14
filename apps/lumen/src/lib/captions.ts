import type { LabCaption } from '../api/lab'

const CC_LANG_KEY = 'cinemaya:cc-lang'

/** Convert SRT text to WebVTT. */
export function srtToVtt(srt: string): string {
  const body = srt
    .replace(/^\uFEFF/, '')
    .replace(/\r+/g, '')
    .trim()
    // SRT timestamps use comma for millis
    .replace(/(\d{2}:\d{2}:\d{2}),(\d{3})/g, '$1.$2')
  return `WEBVTT\n\n${body}\n`
}

export function languageLabel(code?: string | null): string {
  if (!code) return 'Unknown'
  const normalized = code.trim()
  try {
    const display = new Intl.DisplayNames(['en'], { type: 'language' })
    const name = display.of(normalized.length === 3 ? normalized.slice(0, 2) : normalized)
    if (name) return name
  } catch {
    /* fall through */
  }
  return normalized.toUpperCase()
}

export function readSavedCcLang(): string | null {
  try {
    return localStorage.getItem(CC_LANG_KEY)
  } catch {
    return null
  }
}

export function saveCcLang(lang: string | null) {
  try {
    if (!lang) localStorage.removeItem(CC_LANG_KEY)
    else localStorage.setItem(CC_LANG_KEY, lang)
  } catch {
    /* ignore */
  }
}

export async function captionToTrackSrc(caption: LabCaption): Promise<string> {
  const type = (caption.type || '').toLowerCase()
  const looksSrt = type === 'srt' || /\.srt(\?|$)/i.test(caption.url)
  if (!looksSrt) return caption.url

  const res = await fetch(caption.url)
  if (!res.ok) throw new Error(`Caption fetch failed (${res.status})`)
  const text = await res.text()
  const vtt = srtToVtt(text)
  const blob = new Blob([vtt], { type: 'text/vtt' })
  return URL.createObjectURL(blob)
}

export function dedupeCaptions(captions: LabCaption[]): LabCaption[] {
  const seen = new Set<string>()
  const out: LabCaption[] = []
  for (const c of captions) {
    if (!c?.url) continue
    const key = `${(c.language || '').toLowerCase()}|${c.url}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push(c)
  }
  return out
}
