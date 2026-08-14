import { headersForStreamUrl } from '../lib/streamRules'

export type MediaType = 'movie' | 'show'

export interface LabSearchHit {
  tmdbId: string
  type: MediaType
  title: string
  releaseYear: number | null
  overview: string
  /** TMDB ISO 639-1 original language (e.g. en, ja). */
  originalLanguage?: string | null
  /** TMDB anime keyword / ja+Animation — used to gate anime scrapers & Anime4K. */
  isAnime?: boolean
  poster: string | null
}

export interface LabCaption {
  id?: string
  url: string
  originalUrl?: string
  type?: 'srt' | 'vtt' | string
  language?: string | null
  hasCorsRestrictions?: boolean
}

export interface LabPlayable {
  type: 'hls' | 'mp4' | 'file'
  url: string
  originalUrl?: string
  quality?: string
  headers?: Record<string, string>
  captions?: LabCaption[]
  proxied?: boolean
}

function toBase64Url(json: string) {
  const bytes = new TextEncoder().encode(json)
  let binary = ''
  for (const b of bytes) binary += String.fromCharCode(b)
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function clientProxyPath(targetUrl: string, headers: Record<string, string> = {}) {
  return `/api/proxy?p=${toBase64Url(JSON.stringify({ url: targetUrl, headers }))}`
}

/**
 * Host sync used to embed http://127.0.0.1:3847/api/proxy — that only works on the host PC.
 * Rewrite to a same-origin /api/proxy path so Tailscale guests use Vite's proxy.
 * Also wraps bare CDN URLs that match prepareStream rules with proxy + headers.
 */
export function localizeStreamUrl(url: string, extraHeaders?: Record<string, string>): string {
  if (!url) return url
  try {
    if (url.startsWith('/api/proxy')) return url
    const parsed = new URL(url, window.location.origin)
    if (parsed.pathname === '/api/proxy' || parsed.pathname.startsWith('/api/proxy')) {
      return `${parsed.pathname}${parsed.search}`
    }
    if (
      (parsed.hostname === '127.0.0.1' || parsed.hostname === 'localhost') &&
      parsed.pathname.includes('/api/proxy')
    ) {
      return `${parsed.pathname}${parsed.search}`
    }
    if (/^https?:$/i.test(parsed.protocol)) {
      const ruleHeaders = headersForStreamUrl(parsed.toString())
      const headers = { ...ruleHeaders, ...(extraHeaders || {}) }
      if (Object.keys(headers).length > 0) {
        return clientProxyPath(parsed.toString(), headers)
      }
    }
  } catch {
    /* keep */
  }
  return url
}

export function localizeStream(stream: LabStream): LabStream {
  const playHeaders = stream.playable.headers || {}
  const captions = (stream.playable.captions || []).map((c) => ({
    ...c,
    url: localizeStreamUrl(c.url, playHeaders),
  }))
  return {
    ...stream,
    playable: {
      ...stream.playable,
      url: localizeStreamUrl(stream.playable.url, playHeaders),
      captions,
    },
  }
}

export function streamIdentity(stream: LabStream | null | undefined): string {
  if (!stream?.playable) return ''
  // Prefer stable upstream URL — proxy encoding/header order must not change identity.
  const raw = String(stream.playable.originalUrl || stream.playable.url || '')
  let stable = raw
  try {
    if (raw.startsWith('/api/proxy') || raw.includes('/api/proxy?')) {
      const q = raw.includes('?') ? raw.slice(raw.indexOf('?') + 1) : ''
      const p = new URLSearchParams(q).get('p')
      if (p) {
        const decoded = JSON.parse(
          atob(p.replace(/-/g, '+').replace(/_/g, '/')),
        ) as { url?: string }
        if (decoded?.url) stable = decoded.url
      }
    }
  } catch {
    /* keep raw */
  }
  return `${stream.sourceId}|${stream.embedId || ''}|${stable}`
}

export interface LabStream {
  sourceId: string
  sourceName: string
  embedId: string | null
  embedName: string | null
  playable: LabPlayable
  index?: number
}

export interface RaceMedia {
  type: MediaType
  tmdbId: string
  title: string
  releaseYear?: number | string
  season?: number | string
  episode?: number | string
  includeDisabled?: boolean
  concurrency?: number
}

/** "Spring Breakers" + 122081 → "Spring-Breakers-122081" */
export function slugifyTitle(title: string) {
  const slug = title
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .replace(/-{2,}/g, '-')
  return slug || 'title'
}

export function watchSlug(title: string, tmdbId: string | number, type?: MediaType) {
  if (type) return `${slugifyTitle(title)}-${type}-${tmdbId}`
  return `${slugifyTitle(title)}-${tmdbId}`
}

/** Alias used for media + watch path ids */
export function mediaKey(title: string, tmdbId: string | number, type?: MediaType) {
  return watchSlug(title, tmdbId, type)
}

export function parseWatchSlug(
  id: string,
): { slug: string; tmdbId: string; type?: MediaType } | null {
  const typed = /^(.*)-(movie|show)-(\d+)$/.exec(id)
  if (typed) {
    return { slug: typed[1]!, type: typed[2] as MediaType, tmdbId: typed[3]! }
  }
  const match = /^(.*)-(\d+)$/.exec(id)
  if (!match) return null
  return { slug: match[1]!, tmdbId: match[2]! }
}

export function getCachedTitle(
  tmdbId: string,
  type?: MediaType,
): (LabSearchHit & { backdrop?: string | null }) | null {
  if (type) {
    try {
      const typed = sessionStorage.getItem(`lumen:tmdb:${type}:${tmdbId}`)
      if (typed) return JSON.parse(typed)
    } catch {
      /* ignore */
    }
  }
  try {
    const raw = sessionStorage.getItem(`lumen:tmdb:${tmdbId}`)
    if (!raw) return null
    return JSON.parse(raw)
  } catch {
    return null
  }
}

/** Resolve type + tmdbId from a watch/media slug (or legacy tmdb-movie-123). */
export function parseMediaKey(id: string): { type: MediaType; tmdbId: string; pathId: string } | null {
  const legacy = /^tmdb-(movie|show)-(\d+)$/.exec(id)
  if (legacy) {
    return { type: legacy[1] as MediaType, tmdbId: legacy[2]!, pathId: id }
  }
  const watch = parseWatchSlug(id)
  if (!watch) return null
  if (watch.type) {
    return { type: watch.type, tmdbId: watch.tmdbId, pathId: id }
  }
  const cached = getCachedTitle(watch.tmdbId)
  return {
    type: cached?.type || 'movie',
    tmdbId: watch.tmdbId,
    pathId: id,
  }
}

export function partyRoomParam(search: URLSearchParams) {
  return search.get('room') || search.get('watchparty')
}

export async function searchLab(query: string): Promise<{ results: LabSearchHit[]; error?: string }> {
  const res = await fetch(`/api/search?q=${encodeURIComponent(query)}`)
  if (!res.ok) throw new Error(`Search failed (${res.status})`)
  return res.json()
}

export interface LabSeasonInfo {
  seasonNumber: number
  episodeCount: number
  name?: string
}

export interface LabEpisodeInfo {
  episodeNumber: number
  seasonNumber: number
  name: string
  overview: string
  still: string | null
  runtime?: number | null
  airDate?: string | null
}

export interface LabSeasonDetails {
  tmdbId: string
  seasonNumber: number
  name: string
  overview: string
  poster: string | null
  episodes: LabEpisodeInfo[]
}

export interface LabDetails extends LabSearchHit {
  backdrop?: string | null
  seasons?: LabSeasonInfo[]
  numberOfSeasons?: number
}

/**
 * Sync next-episode hint from season metadata only.
 * Absolute-numbered anime (e.g. One Piece S21 eps 892–1088) have episodeCount as
 * length, not max episode number — those need resolveNextEpisode for season borders.
 */
export function nextEpisodeInSeries(
  seasons: LabSeasonInfo[] | undefined,
  season: number,
  episode: number,
  currentSeasonEpisodes?: LabEpisodeInfo[],
): { season: number; episode: number } | null {
  if (!seasons?.length) return null
  const ordered = [...seasons]
    .filter((s) => s.seasonNumber > 0 && s.episodeCount > 0)
    .sort((a, b) => a.seasonNumber - b.seasonNumber)
  if (!ordered.length) return null

  if (currentSeasonEpisodes?.length) {
    const eps = [...currentSeasonEpisodes].sort((a, b) => a.episodeNumber - b.episodeNumber)
    const nextInSeason = eps.find((e) => e.episodeNumber > episode)
    if (nextInSeason) return { season, episode: nextInSeason.episodeNumber }
    const nextSeason = ordered.find((s) => s.seasonNumber > season)
    if (!nextSeason) return null
    // Without the next season's list, avoid guessing E1 (wrong for absolute shows).
    return null
  }

  const current = ordered.find((s) => s.seasonNumber === season)
  if (current) {
    // Absolute numbering: current ep number is past the season length.
    if (episode > current.episodeCount) {
      return { season, episode: episode + 1 }
    }
    if (episode < current.episodeCount) {
      return { season, episode: episode + 1 }
    }
  }
  const nextSeason = ordered.find((s) => s.seasonNumber > season)
  // Relative seasons end at episodeCount and start the next at E1.
  if (nextSeason && current && episode <= current.episodeCount) {
    return { season: nextSeason.seasonNumber, episode: 1 }
  }
  return null
}

/** Accurate next episode using TMDB season episode lists (handles absolute numbering). */
export async function resolveNextEpisode(
  tmdbId: string,
  seasons: LabSeasonInfo[] | undefined,
  season: number,
  episode: number,
): Promise<{ season: number; episode: number } | null> {
  if (!tmdbId || !seasons?.length) return null
  const ordered = [...seasons]
    .filter((s) => s.seasonNumber > 0 && s.episodeCount > 0)
    .sort((a, b) => a.seasonNumber - b.seasonNumber)
  if (!ordered.length) return null

  try {
    const details = await fetchSeason(tmdbId, season)
    const eps = [...details.episodes].sort((a, b) => a.episodeNumber - b.episodeNumber)
    const nextInSeason = eps.find((e) => e.episodeNumber > episode)
    if (nextInSeason) return { season, episode: nextInSeason.episodeNumber }
  } catch {
    const fallback = nextEpisodeInSeries(seasons, season, episode)
    if (fallback && fallback.season === season) return fallback
  }

  const nextSeason = ordered.find((s) => s.seasonNumber > season)
  if (!nextSeason) return null

  try {
    const details = await fetchSeason(tmdbId, nextSeason.seasonNumber)
    const first = [...details.episodes].sort((a, b) => a.episodeNumber - b.episodeNumber)[0]
    if (first) return { season: nextSeason.seasonNumber, episode: first.episodeNumber }
  } catch {
    // ignore
  }

  const current = ordered.find((s) => s.seasonNumber === season)
  // Never invent E1 after an absolute-numbered season — that races series premiere.
  if (current && episode > current.episodeCount) return null
  return { season: nextSeason.seasonNumber, episode: 1 }
}

export async function fetchDetails(type: MediaType, tmdbId: string): Promise<LabDetails> {
  const res = await fetch(
    `/api/details?type=${encodeURIComponent(type)}&id=${encodeURIComponent(tmdbId)}`,
  )
  if (!res.ok) throw new Error(`Details failed (${res.status})`)
  return res.json()
}

export async function fetchSeason(tmdbId: string, season: number): Promise<LabSeasonDetails> {
  const res = await fetch(
    `/api/season?id=${encodeURIComponent(tmdbId)}&season=${encodeURIComponent(String(season))}`,
  )
  if (!res.ok) throw new Error(`Season failed (${res.status})`)
  return res.json()
}

export interface ExternalSubtitle {
  id: string
  language: string
  url: string | null
  fileId?: string | number | null
  type?: string
  label?: string | null
  source: string
  hearingImpaired?: boolean
}

export async function fetchExternalSubtitles(opts: {
  type: MediaType
  tmdbId: string
  season?: number
  episode?: number
  imdbId?: string
}): Promise<{ results: ExternalSubtitle[]; hint?: string | null }> {
  const params = new URLSearchParams({
    type: opts.type,
    tmdbId: opts.tmdbId,
  })
  if (opts.season) params.set('season', String(opts.season))
  if (opts.episode) params.set('episode', String(opts.episode))
  if (opts.imdbId) params.set('imdbId', opts.imdbId)
  const res = await fetch(`/api/subtitles?${params}`)
  if (!res.ok) throw new Error(`Subtitles failed (${res.status})`)
  return res.json()
}

export async function resolveExternalSubtitleUrl(fileId: string | number): Promise<string> {
  const res = await fetch('/api/subtitles/download', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fileId }),
  })
  const data = (await res.json().catch(() => ({}))) as { url?: string; error?: string }
  if (!res.ok || !data.url) throw new Error(data.error || `Subtitle download failed (${res.status})`)
  return data.url
}

export type AniSkipApiResult = {
  found: boolean
  malId: number | null
  episode: number
  results: Array<{
    skipId: string
    skipType: string
    startTime: number
    endTime: number
    episodeLength?: number
  }>
  error?: string
}

export async function fetchAniSkip(opts: {
  title?: string
  tmdbId?: string
  episode: number
  episodeLength?: number
  year?: number | null
  malId?: number
}): Promise<AniSkipApiResult> {
  const params = new URLSearchParams({
    episode: String(opts.episode),
  })
  if (opts.title) params.set('title', opts.title)
  if (opts.tmdbId) params.set('tmdbId', opts.tmdbId)
  if (opts.episodeLength && opts.episodeLength > 0) {
    params.set('episodeLength', String(Math.round(opts.episodeLength)))
  }
  if (opts.year) params.set('year', String(opts.year))
  if (opts.malId) params.set('malId', String(opts.malId))
  const res = await fetch(`/api/aniskip?${params}`)
  if (!res.ok) throw new Error(`AniSkip failed (${res.status})`)
  return res.json()
}

export async function fetchPopular(movies = 5, tv = 10): Promise<{
  movies: LabDetails[]
  tv: LabDetails[]
}> {
  const res = await fetch(`/api/popular?movies=${movies}&tv=${tv}`)
  if (!res.ok) throw new Error(`Popular failed (${res.status})`)
  return res.json()
}

export type DiscoverSection = 'movies' | 'tv' | 'anime'
export type DiscoverRail = 'popular' | 'newest' | 'top' | 'films' | 'airing'

export async function fetchDiscover(
  section: DiscoverSection,
  rail: DiscoverRail = 'popular',
  limit = 16,
): Promise<LabDetails[]> {
  const res = await fetch(
    `/api/discover?section=${encodeURIComponent(section)}&rail=${encodeURIComponent(rail)}&limit=${limit}`,
  )
  if (!res.ok) throw new Error(`Discover failed (${res.status})`)
  const data = (await res.json()) as { results?: LabDetails[] }
  return data.results || []
}

export interface PartyRoomInfo {
  exists: boolean
  roomCode: string
  contentId: string | null
  title: string | null
  hostName: string | null
  viewers: number
  stream: LabStream | null
}

export async function lookupPartyRoom(code: string): Promise<PartyRoomInfo> {
  const res = await fetch(`/api/party/room/${encodeURIComponent(code.trim())}`)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error((data as { error?: string }).error || `Room ${code} not found`)
  }
  return data as PartyRoomInfo
}

export interface OpenPartyRoom {
  roomCode: string
  contentId: string | null
  title: string | null
  hostName: string | null
  viewers: number
  updatedAt: number | null
  hasStream: boolean
}

export async function fetchOpenRooms(): Promise<OpenPartyRoom[]> {
  const res = await fetch('/api/party/rooms')
  if (!res.ok) throw new Error(`Open rooms failed (${res.status})`)
  const data = (await res.json()) as { rooms?: OpenPartyRoom[] }
  return data.rooms || []
}

export function partyInviteUrl(contentId: string, roomCode: string, base = '/watch') {
  const root = base.replace(/\/$/, '') || '/watch'
  const url = new URL(`${root}/${contentId}`, window.location.origin)
  url.searchParams.set('party', '1')
  url.searchParams.set('room', roomCode)
  return url.toString()
}

export function watchUrl(
  contentId: string,
  opts?: { party?: boolean; room?: string; base?: string },
) {
  const root = (opts?.base || '/watch').replace(/\/$/, '') || '/watch'
  const url = new URL(`${root}/${contentId}`, window.location.origin)
  if (opts?.party) url.searchParams.set('party', '1')
  if (opts?.room) url.searchParams.set('room', opts.room)
  return `${url.pathname}${url.search}`
}

/** CINEMAYA player path */
export function demoWatchUrl(contentId: string, opts?: { party?: boolean; room?: string }) {
  return watchUrl(contentId, { ...opts, base: '/watch' })
}

export function demoMediaPath(contentId: string) {
  return `/media/${contentId}`
}

export function cacheTitle(hit: LabSearchHit & { backdrop?: string | null }) {
  const pathId = watchSlug(hit.title, hit.tmdbId, hit.type)
  const payload = JSON.stringify({ ...hit, pathId })
  sessionStorage.setItem(`lumen:tmdb:${hit.type}:${hit.tmdbId}`, payload)
  sessionStorage.setItem(`lumen:tmdb:${hit.tmdbId}`, payload)
  sessionStorage.setItem(`lumen:title:${pathId}`, payload)
}

export async function resolveTitleFromPath(pathId: string): Promise<LabDetails | null> {
  const parsed = parseMediaKey(pathId)
  if (!parsed) return null
  const watch = parseWatchSlug(pathId)
  const cached = getCachedTitle(parsed.tmdbId, parsed.type)
  if (cached) {
    // Reject stale untyped cache that doesn't match the path slug (movie/TV ID collisions).
    const slugOk = !watch?.slug || slugifyTitle(cached.title) === watch.slug
    const typeOk = !watch?.type || cached.type === parsed.type
    // Search/rail cache often has no seasons — still hit /api/details for TV episode lists.
    const needsSeasons =
      cached.type === 'show' && !(cached.seasons && cached.seasons.length > 0)
    if (slugOk && typeOk && !needsSeasons) return cached
  }
  // Prefer the parsed type; only fall back to the other type for legacy untyped URLs.
  const order: MediaType[] = watch?.type
    ? [parsed.type]
    : [parsed.type, parsed.type === 'movie' ? 'show' : 'movie']
  for (const type of order) {
    try {
      const details = await fetchDetails(type, parsed.tmdbId)
      if (watch?.slug && slugifyTitle(details.title) !== watch.slug) continue
      cacheTitle(details)
      return details
    } catch {
      /* try next */
    }
  }
  // Last resort: incomplete cache is better than nothing.
  if (cached) return cached
  return null
}

export type RaceHandlers = {
  onStart?: (data: { total: number }) => void
  onProgress?: (data: {
    tried: number
    total: number
    id: string
    name: string
    status: string
  }) => void
  onStream?: (stream: LabStream) => void
  onDone?: (data: { ms: number; tried: number; total: number; playableCount: number }) => void
  onError?: (message: string) => void
}

const RACE_MAX_ATTEMPTS = 3

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Aborted', 'AbortError'))
      return
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    const onAbort = () => {
      clearTimeout(timer)
      reject(new DOMException('Aborted', 'AbortError'))
    }
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

async function raceSourcesOnce(
  media: RaceMedia,
  handlers: RaceHandlers,
  signal?: AbortSignal,
): Promise<{ playableCount: number }> {
  const res = await fetch('/api/race', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      // Disabled scrapers (e.g. Aether-API) often 403 — only include when asked.
      includeDisabled: media.includeDisabled === true,
      concurrency: media.concurrency ?? 12,
      type: media.type,
      tmdbId: media.tmdbId,
      title: media.title,
      releaseYear: media.releaseYear,
      season: media.season,
      episode: media.episode,
    }),
    signal,
  })

  if (!res.ok || !res.body) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as { error?: string }).error || `Race failed (${res.status})`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let playableCount = 0

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() || ''

    for (const chunk of chunks) {
      const lines = chunk.split('\n')
      let event = 'message'
      let dataLine = ''
      for (const line of lines) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        if (line.startsWith('data:')) dataLine += line.slice(5).trim()
      }
      if (!dataLine) continue
      const data = JSON.parse(dataLine)
      if (event === 'start') handlers.onStart?.(data)
      else if (event === 'progress') handlers.onProgress?.(data)
      else if (event === 'stream') {
        playableCount += 1
        handlers.onStream?.(data)
      } else if (event === 'done') {
        playableCount = Number(data.playableCount) || playableCount
        handlers.onDone?.(data)
      } else if (event === 'error') handlers.onError?.(data.error || 'Race error')
    }
  }

  return { playableCount }
}

/** Race providers; if the first pass finds nothing, retry a couple times. */
export async function raceSources(
  media: RaceMedia,
  handlers: RaceHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let lastError: Error | null = null
  let totals = { ms: 0, tried: 0, total: 0, playableCount: 0 }

  for (let attempt = 1; attempt <= RACE_MAX_ATTEMPTS; attempt++) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')

    if (attempt > 1) {
      handlers.onProgress?.({
        tried: 0,
        total: totals.total,
        id: 'retry',
        name: `Retry ${attempt}/${RACE_MAX_ATTEMPTS}`,
        status: 'retry',
      })
      await sleep(400 * (attempt - 1), signal)
    }

    const isFinal = attempt === RACE_MAX_ATTEMPTS
    let playableCount = 0

    try {
      const result = await raceSourcesOnce(
        media,
        {
          onStart: (data) => {
            totals.total = data.total
            handlers.onStart?.(data)
          },
          onProgress: handlers.onProgress,
          onStream: (stream) => {
            playableCount += 1
            handlers.onStream?.(stream)
          },
          onDone: (data) => {
            totals = {
              ms: (totals.ms || 0) + (data.ms || 0),
              tried: data.tried,
              total: data.total,
              playableCount: data.playableCount,
            }
            playableCount = data.playableCount
            // Hold "done" until we succeed or exhaust retries (keeps racing UI on).
            if (data.playableCount > 0 || isFinal) {
              handlers.onDone?.({ ...data, ms: totals.ms, playableCount: data.playableCount })
            }
          },
          onError: (message) => {
            if (isFinal) handlers.onError?.(message)
          },
        },
        signal,
      )
      playableCount = result.playableCount
      if (playableCount > 0) return
      lastError = null
    } catch (e) {
      const err = e as Error
      if (err.name === 'AbortError') throw err
      lastError = err
      if (isFinal) throw err
    }
  }

  if (lastError) throw lastError
}
