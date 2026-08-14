import { useEffect, useState } from 'react'
import {
  cacheTitle,
  fetchDiscover,
  type DiscoverRail,
  type DiscoverSection,
  type LabDetails,
} from '../api/lab'
import { DemoHero } from './components/DemoHero'
import { DemoRail } from './components/DemoRail'

type CatalogConfig = {
  section: DiscoverSection
  heading: string
  tagline: string
  rails: { id: string; title: string; rail: DiscoverRail }[]
}

const CONFIG: Record<string, CatalogConfig> = {
  movies: {
    section: 'movies',
    heading: 'Movies',
    tagline: 'Popular picks, new releases, and highly rated films.',
    rails: [
      { id: 'popular', title: 'Popular', rail: 'popular' },
      { id: 'newest', title: 'Newest', rail: 'newest' },
      { id: 'top', title: 'Top Rated', rail: 'top' },
    ],
  },
  tv: {
    section: 'tv',
    heading: 'TV',
    tagline: 'Series worth bingeing — popular, new, and critically loved.',
    rails: [
      { id: 'popular', title: 'Popular', rail: 'popular' },
      { id: 'newest', title: 'Newest', rail: 'newest' },
      { id: 'top', title: 'Top Rated', rail: 'top' },
    ],
  },
  anime: {
    section: 'anime',
    heading: 'Anime',
    tagline: 'Anime-only rails via TMDB keyword — popular, airing, new, films, and top rated.',
    rails: [
      { id: 'popular', title: 'Popular', rail: 'popular' },
      { id: 'airing', title: 'Airing Now', rail: 'airing' },
      { id: 'newest', title: 'Newest', rail: 'newest' },
      { id: 'films', title: 'Films', rail: 'films' },
      { id: 'top', title: 'Top Rated', rail: 'top' },
    ],
  },
}

type Props = {
  kind: 'movies' | 'tv' | 'anime'
}

export function DemoCatalogPage({ kind }: Props) {
  const config = CONFIG[kind]
  const [rails, setRails] = useState<Record<string, LabDetails[]>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    const cfg = CONFIG[kind]
    setLoading(true)
    setError('')
    setRails({})

    Promise.all(
      cfg.rails.map(async (r) => {
        const items = await fetchDiscover(cfg.section, r.rail, 18)
        return [r.id, items] as const
      }),
    )
      .then((entries) => {
        if (cancelled) return
        const next: Record<string, LabDetails[]> = {}
        for (const [id, items] of entries) {
          next[id] = items
          items.forEach((hit) => cacheTitle(hit))
        }
        setRails(next)
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
  }, [kind])

  const featured = rails.popular?.[0] || rails.newest?.[0] || null

  return (
    <>
      {featured ? (
        <DemoHero featured={featured} />
      ) : (
        <section className="demo-hero">
          <div className="demo-hero-scrim" />
          <div className="demo-hero-body">
            <p className="demo-display demo-hero-brand">CINEMAYA</p>
            <p className="demo-hero-tag">{config.heading}</p>
            <p className="demo-hero-support">
              {loading ? 'Loading catalog…' : error || config.tagline}
            </p>
          </div>
        </section>
      )}

      <main className="demo-main">
        <header className="demo-catalog-head">
          <h1 className="demo-display demo-catalog-title">{config.heading}</h1>
          <p className="demo-catalog-tag">{config.tagline}</p>
        </header>

        {error && featured ? <p className="demo-rail demo-error">{error}</p> : null}

        {config.rails.map((r) => (
          <DemoRail key={r.id} id={r.id} title={r.title} items={rails[r.id] || []} />
        ))}

        {loading ? <p className="demo-load-more">Loading rails…</p> : null}
      </main>
    </>
  )
}
