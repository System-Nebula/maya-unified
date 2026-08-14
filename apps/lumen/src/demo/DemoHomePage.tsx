import { useCallback, useEffect, useRef, useState } from 'react'
import {
  cacheTitle,
  fetchPopular,
  searchLab,
  type LabDetails,
  type LabSearchHit,
} from '../api/lab'
import {
  listContinueWatching,
  listWatchHistory,
  type WatchHistoryEntry,
} from '../lib/watchHistory'
import { DemoHero } from './components/DemoHero'
import { DemoRail } from './components/DemoRail'
import { DemoWatchHistoryRail } from './components/DemoWatchHistoryRail'

type Rail = {
  id: string
  title: string
  items: Array<LabDetails | LabSearchHit>
}

const EXTRA_CATEGORIES: { id: string; title: string; q: string }[] = [
  { id: 'trending-now', title: 'Trending Now', q: '2024' },
  { id: 'action', title: 'Action & Adventure', q: 'action' },
  { id: 'comedy', title: 'Comedy', q: 'comedy' },
  { id: 'thriller', title: 'Thrillers', q: 'thriller' },
  { id: 'scifi', title: 'Sci-Fi', q: 'science fiction' },
  { id: 'horror', title: 'Horror', q: 'horror' },
  { id: 'drama', title: 'Drama', q: 'drama' },
  { id: 'animation', title: 'Animation', q: 'animation' },
  { id: 'fantasy', title: 'Fantasy', q: 'fantasy' },
  { id: 'crime', title: 'Crime', q: 'crime' },
  { id: 'romance', title: 'Romance', q: 'romance' },
  { id: 'documentary', title: 'Documentaries', q: 'documentary' },
  { id: 'mystery', title: 'Mystery', q: 'mystery' },
  { id: 'war', title: 'War & History', q: 'war' },
  { id: 'family', title: 'Family', q: 'family' },
]

const BATCH = 2

export function DemoHomePage() {
  const [movies, setMovies] = useState<LabDetails[]>([])
  const [tv, setTv] = useState<LabDetails[]>([])
  const [continueWatching, setContinueWatching] = useState<WatchHistoryEntry[]>([])
  const [recentHistory, setRecentHistory] = useState<WatchHistoryEntry[]>([])
  const [extraRails, setExtraRails] = useState<Rail[]>([])
  const [nextCat, setNextCat] = useState(0)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const sentinelRef = useRef<HTMLDivElement>(null)
  const loadingRef = useRef(false)

  const refreshHistory = useCallback(() => {
    void Promise.all([listContinueWatching(24), listWatchHistory(36)])
      .then(([cont, hist]) => {
        setContinueWatching(cont)
        const contKeys = new Set(cont.map((c) => c.titleKey))
        setRecentHistory(hist.filter((h) => !contKeys.has(h.titleKey)).slice(0, 24))
      })
      .catch(() => {
        /* IndexedDB unavailable */
      })
  }, [])

  useEffect(() => {
    refreshHistory()
    const onVis = () => {
      if (document.visibilityState === 'visible') refreshHistory()
    }
    window.addEventListener('focus', refreshHistory)
    document.addEventListener('visibilitychange', onVis)
    return () => {
      window.removeEventListener('focus', refreshHistory)
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [refreshHistory])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetchPopular(16, 16)
      .then((data) => {
        if (cancelled) return
        const m = data.movies || []
        const t = data.tv || []
        ;[...m, ...t].forEach((hit) => cacheTitle(hit))
        setMovies(m)
        setTv(t)
        setError('')
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const loadMore = useCallback(async () => {
    if (loadingRef.current || nextCat >= EXTRA_CATEGORIES.length) return
    loadingRef.current = true
    setLoadingMore(true)

    const batch = EXTRA_CATEGORIES.slice(nextCat, nextCat + BATCH)
    const loaded: Rail[] = []

    await Promise.all(
      batch.map(async (cat) => {
        try {
          const data = await searchLab(cat.q)
          const hits = (data.results || []).slice(0, 14)
          if (!hits.length) return
          hits.forEach((hit) => cacheTitle(hit))
          loaded.push({ id: cat.id, title: cat.title, items: hits })
        } catch {
          /* skip empty/failed category */
        }
      }),
    )

    // Keep category order stable
    loaded.sort(
      (a, b) =>
        EXTRA_CATEGORIES.findIndex((c) => c.id === a.id) -
        EXTRA_CATEGORIES.findIndex((c) => c.id === b.id),
    )

    setExtraRails((prev) => [...prev, ...loaded])
    setNextCat((n) => n + BATCH)
    loadingRef.current = false
    setLoadingMore(false)
  }, [nextCat])

  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) void loadMore()
      },
      { rootMargin: '400px 0px' },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [loadMore])

  const featured = movies[0]
  const hasMore = nextCat < EXTRA_CATEGORIES.length

  return (
    <>
      {featured ? (
        <DemoHero featured={featured} />
      ) : (
        <section className="demo-hero">
          <div className="demo-hero-scrim" />
          <div className="demo-hero-body">
            <p className="demo-display demo-hero-brand">CINEMAYA</p>
            <p className="demo-hero-tag">A million films built for friends</p>
            <p className="demo-hero-support">
              {loading ? 'Loading the archive…' : error || 'Popular feed unavailable.'}
            </p>
          </div>
        </section>
      )}

      <main className="demo-main">
        {error && featured ? <p className="demo-rail demo-error">{error}</p> : null}
        <DemoWatchHistoryRail
          id="continue"
          title="Continue Watching"
          items={continueWatching}
          variant="continue"
        />
        <DemoWatchHistoryRail
          id="history"
          title="Recently Watched"
          items={recentHistory}
          variant="history"
        />
        <DemoRail id="movies" title="Top Movies" items={movies} />
        <DemoRail id="tv" title="Top TV" items={tv} />
        {extraRails.map((rail) => (
          <DemoRail key={rail.id} id={rail.id} title={rail.title} items={rail.items} />
        ))}
        <div ref={sentinelRef} className="demo-scroll-sentinel" aria-hidden />
        {loadingMore ? <p className="demo-load-more">Loading more…</p> : null}
        {!hasMore && extraRails.length > 0 ? (
          <p className="demo-load-more demo-load-more-done">End of the archive</p>
        ) : null}
      </main>
    </>
  )
}
