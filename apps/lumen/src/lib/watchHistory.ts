import { mediaKey, type MediaType } from '../api/lab'

const DB_NAME = 'cinemaya-watch'
const DB_VERSION = 1
const STORE = 'progress'

export type WatchHistoryEntry = {
  /** Unique per episode/movie: movie:123 | show:456:s2e5 */
  id: string
  /** Series/movie key for dedupe: movie:123 | show:456 */
  titleKey: string
  pathId: string
  type: MediaType
  tmdbId: string
  season?: number
  episode?: number
  title: string
  poster: string | null
  backdrop: string | null
  year: number | null
  currentTime: number
  duration: number
  percent: number
  completed: boolean
  updatedAt: number
}

export function watchProgressId(
  type: MediaType,
  tmdbId: string,
  season?: number,
  episode?: number,
): string {
  if (type === 'movie') return `movie:${tmdbId}`
  return `show:${tmdbId}:s${season || 1}e${episode || 1}`
}

export function watchTitleKey(type: MediaType, tmdbId: string): string {
  return `${type}:${tmdbId}`
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onerror = () => reject(req.error || new Error('IndexedDB open failed'))
    req.onsuccess = () => resolve(req.result)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE)) {
        const store = db.createObjectStore(STORE, { keyPath: 'id' })
        store.createIndex('updatedAt', 'updatedAt')
        store.createIndex('titleKey', 'titleKey')
      }
    }
  })
}

function idbReq<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error || new Error('IndexedDB request failed'))
  })
}

export async function upsertWatchProgress(
  partial: Omit<WatchHistoryEntry, 'id' | 'titleKey' | 'pathId' | 'percent' | 'updatedAt'> & {
    pathId?: string
    completed?: boolean
  },
): Promise<WatchHistoryEntry> {
  const season = partial.type === 'show' ? partial.season || 1 : undefined
  const episode = partial.type === 'show' ? partial.episode || 1 : undefined
  const id = watchProgressId(partial.type, partial.tmdbId, season, episode)
  const duration = Math.max(0, Number(partial.duration) || 0)
  const currentTime = Math.max(0, Number(partial.currentTime) || 0)
  const percent = duration > 0 ? Math.min(1, currentTime / duration) : 0
  const completed =
    partial.completed === true || (duration > 60 && percent >= 0.92)

  const entry: WatchHistoryEntry = {
    id,
    titleKey: watchTitleKey(partial.type, partial.tmdbId),
    pathId:
      partial.pathId ||
      mediaKey(partial.title, partial.tmdbId, partial.type),
    type: partial.type,
    tmdbId: partial.tmdbId,
    season,
    episode,
    title: partial.title,
    poster: partial.poster ?? null,
    backdrop: partial.backdrop ?? null,
    year: partial.year ?? null,
    currentTime: completed ? duration : currentTime,
    duration,
    percent: completed ? 1 : percent,
    completed,
    updatedAt: Date.now(),
  }

  const db = await openDb()
  try {
    const tx = db.transaction(STORE, 'readwrite')
    await idbReq(tx.objectStore(STORE).put(entry))
  } finally {
    db.close()
  }
  return entry
}

export async function getWatchProgress(
  type: MediaType,
  tmdbId: string,
  season?: number,
  episode?: number,
): Promise<WatchHistoryEntry | null> {
  const id = watchProgressId(type, tmdbId, season, episode)
  const db = await openDb()
  try {
    const tx = db.transaction(STORE, 'readonly')
    const row = await idbReq(tx.objectStore(STORE).get(id))
    return (row as WatchHistoryEntry) || null
  } finally {
    db.close()
  }
}

export async function getLatestForTitle(
  type: MediaType,
  tmdbId: string,
): Promise<WatchHistoryEntry | null> {
  const key = watchTitleKey(type, tmdbId)
  const db = await openDb()
  try {
    const tx = db.transaction(STORE, 'readonly')
    const idx = tx.objectStore(STORE).index('titleKey')
    const rows = (await idbReq(idx.getAll(key))) as WatchHistoryEntry[]
    if (!rows?.length) return null
    rows.sort((a, b) => b.updatedAt - a.updatedAt)
    return rows[0] || null
  } finally {
    db.close()
  }
}

async function allProgress(): Promise<WatchHistoryEntry[]> {
  const db = await openDb()
  try {
    const tx = db.transaction(STORE, 'readonly')
    const rows = (await idbReq(tx.objectStore(STORE).getAll())) as WatchHistoryEntry[]
    return Array.isArray(rows) ? rows : []
  } finally {
    db.close()
  }
}

/** In-progress titles, newest first, one card per show/movie. */
export async function listContinueWatching(limit = 24): Promise<WatchHistoryEntry[]> {
  const rows = await allProgress()
  const eligible = rows
    .filter((r) => !r.completed && r.currentTime >= 20 && r.percent < 0.92)
    .sort((a, b) => b.updatedAt - a.updatedAt)
  const seen = new Set<string>()
  const out: WatchHistoryEntry[] = []
  for (const row of eligible) {
    if (seen.has(row.titleKey)) continue
    seen.add(row.titleKey)
    out.push(row)
    if (out.length >= limit) break
  }
  return out
}

/** Recently touched titles (including completed), newest first. */
export async function listWatchHistory(limit = 36): Promise<WatchHistoryEntry[]> {
  const rows = await allProgress()
  rows.sort((a, b) => b.updatedAt - a.updatedAt)
  const seen = new Set<string>()
  const out: WatchHistoryEntry[] = []
  for (const row of rows) {
    if (seen.has(row.titleKey)) continue
    seen.add(row.titleKey)
    out.push(row)
    if (out.length >= limit) break
  }
  return out
}

export async function removeWatchProgress(id: string): Promise<void> {
  const db = await openDb()
  try {
    const tx = db.transaction(STORE, 'readwrite')
    await idbReq(tx.objectStore(STORE).delete(id))
  } finally {
    db.close()
  }
}

export function formatResumeLabel(entry: WatchHistoryEntry): string {
  if (entry.type === 'show' && entry.season && entry.episode) {
    const ep = `S${entry.season}E${entry.episode}`
    if (entry.completed) return `${ep} · Watched`
    return ep
  }
  if (entry.completed) return 'Watched'
  if (entry.duration > entry.currentTime + 30) {
    const left = Math.max(1, Math.round((entry.duration - entry.currentTime) / 60))
    return `${left}m left`
  }
  const mins = Math.max(1, Math.round(entry.currentTime / 60))
  return `${mins}m in`
}
