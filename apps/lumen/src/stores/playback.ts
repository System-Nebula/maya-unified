import { create } from 'zustand'
import { getCachedTitle, localizeStream, type LabStream, type MediaType } from '../api/lab'
import {
  pickStreamIndex,
  readAudioMode,
  resolveAudioMode,
} from '../lib/audioMode'

export interface PlaybackTitle {
  id: string
  type: MediaType
  tmdbId: string
  title: string
  year: number | null
  overview: string
  poster: string | null
  backdrop: string | null
  season?: number
  episode?: number
  isAnime?: boolean
}

interface PlaybackState {
  title: PlaybackTitle | null
  streams: LabStream[]
  activeIndex: number
  racing: boolean
  raceTried: number
  raceTotal: number
  raceMessage: string
  setTitle: (title: PlaybackTitle) => void
  resetStreams: () => void
  addStream: (stream: LabStream) => void
  setActiveIndex: (index: number) => void
  setRaceProgress: (partial: {
    racing?: boolean
    raceTried?: number
    raceTotal?: number
    raceMessage?: string
  }) => void
}

export const usePlaybackStore = create<PlaybackState>((set, get) => ({
  title: null,
  streams: [],
  activeIndex: -1,
  racing: false,
  raceTried: 0,
  raceTotal: 0,
  raceMessage: '',
  setTitle: (title) => set({ title }),
  resetStreams: () => set({ streams: [], activeIndex: -1 }),
  addStream: (stream) => {
    const localized = localizeStream(stream)
    const key = `${localized.sourceId}|${localized.embedId || ''}|${localized.playable.originalUrl || localized.playable.url}`
    const existing = get().streams
    if (
      existing.some(
        (s) =>
          `${s.sourceId}|${s.embedId || ''}|${s.playable.originalUrl || s.playable.url}` === key,
      )
    ) {
      return
    }
    const streams = [...existing, localized]
    const current = get().activeIndex
    // Only auto-attach when nothing is playing yet. Never steal the user's source
    // when another provider finishes later in the race.
    let activeIndex = current
    if (current < 0) {
      const mode = readAudioMode()
      const tmdbId = get().title?.tmdbId
      const originalLanguage = tmdbId
        ? getCachedTitle(tmdbId, get().title?.type)?.originalLanguage || null
        : null
      const preferred = pickStreamIndex(streams, mode, originalLanguage)
      const effectiveMode = resolveAudioMode(mode, originalLanguage)
      activeIndex =
        preferred >= 0 ? preferred : effectiveMode === 'any' ? 0 : -1
    }
    set({ streams, activeIndex })
  },
  setActiveIndex: (index) => set({ activeIndex: index }),
  setRaceProgress: (partial) => set(partial),
}))

export function streamKindOf(stream: LabStream | undefined): 'hls' | 'file' {
  if (!stream?.playable) return 'file'
  if (stream.playable.type === 'hls') return 'hls'
  const url = stream.playable.originalUrl || stream.playable.url || ''
  // Anime sources often ship HLS masters mislabeled as mp4/file.
  if (/\.m3u8(\?|$)/i.test(url)) return 'hls'
  try {
    if (url.includes('/api/proxy')) {
      const q = url.includes('?') ? url.slice(url.indexOf('?') + 1) : ''
      const p = new URLSearchParams(q).get('p')
      if (p) {
        const pad = p.length % 4 === 0 ? p : p + '='.repeat(4 - (p.length % 4))
        const decoded = JSON.parse(
          atob(pad.replace(/-/g, '+').replace(/_/g, '/')),
        ) as { url?: string }
        if (decoded?.url && /\.m3u8(\?|$)/i.test(decoded.url)) return 'hls'
      }
    }
  } catch {
    /* ignore */
  }
  return 'file'
}
