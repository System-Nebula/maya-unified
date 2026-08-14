import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { cacheTitle, fetchPopular, mediaKey, type LabDetails } from '../api/lab'
import { MediaCard } from '../components/MediaCard'

export function HomePage() {
  const [movies, setMovies] = useState<LabDetails[]>([])
  const [tv, setTv] = useState<LabDetails[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetchPopular(5, 10)
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

  const featured = movies[0]

  return (
    <div className="relative overflow-hidden">
      <div className="lightbar" aria-hidden />

      <section className="relative mx-auto max-w-6xl px-4 pb-8 pt-10 md:px-6 md:pt-16">
        <p className="text-sm font-medium text-accent">Lumen</p>
        <h1 className="mt-2 max-w-xl text-4xl font-bold tracking-tight md:text-5xl">
          Search. Race. Play.
          <span className="block text-text-muted">Watch together over Tailscale.</span>
        </h1>
        <p className="mt-4 max-w-lg text-text-muted">
          Popular titles from TMDB, every source provider, proxied playback, and watch-party sync
          across devices.
        </p>
        {error ? (
          <p className="mt-3 text-sm text-danger">
            Popular feed unavailable ({error}). Is the lab running?
          </p>
        ) : null}
      </section>

      {featured ? (
        <section className="relative mx-auto max-w-6xl px-4 md:px-6">
          <div className="overflow-hidden rounded-2xl border border-white/5 bg-bg-elevated">
            <div className="grid md:grid-cols-[1.2fr_1fr]">
              <div className="relative min-h-[220px] bg-bg-hover">
                {featured.backdrop || featured.poster ? (
                  <img
                    src={featured.backdrop || featured.poster || ''}
                    alt=""
                    className="absolute inset-0 h-full w-full object-cover opacity-70"
                  />
                ) : null}
                <div className="absolute inset-0 bg-gradient-to-r from-bg-elevated via-bg-elevated/80 to-transparent" />
              </div>
              <div className="relative flex flex-col justify-center p-6 md:p-8">
                <span className="text-xs uppercase tracking-wider text-text-dim">
                  Popular movie
                </span>
                <h2 className="mt-1 text-2xl font-bold">{featured.title}</h2>
                <p className="mt-2 line-clamp-3 text-sm text-text-muted">{featured.overview}</p>
                <Link
                  to={`/media/${mediaKey(featured.title, featured.tmdbId, featured.type)}`}
                  className="mt-5 inline-flex w-fit rounded-xl bg-white px-5 py-2.5 text-sm font-semibold text-black hover:bg-white/90"
                >
                  Open
                </Link>
              </div>
            </div>
          </div>
        </section>
      ) : loading ? (
        <p className="mx-auto max-w-6xl px-4 text-sm text-text-muted md:px-6">Loading popular…</p>
      ) : null}

      <section className="mx-auto max-w-6xl px-4 py-12 md:px-6">
        <h2 className="mb-4 text-lg font-semibold">Top 5 movies</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-5 md:gap-4">
          {movies.map((item) => (
            <MediaCard
              key={`movie-${item.tmdbId}`}
              item={{
                id: mediaKey(item.title, item.tmdbId, item.type),
                title: item.title,
                year: item.releaseYear,
                poster: item.poster,
                subtitle: item.releaseYear ? `Movie · ${item.releaseYear}` : 'Movie',
              }}
            />
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 pb-16 md:px-6">
        <h2 className="mb-4 text-lg font-semibold">Top 10 TV shows</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-5 md:gap-4">
          {tv.map((item) => (
            <MediaCard
              key={`show-${item.tmdbId}`}
              item={{
                id: mediaKey(item.title, item.tmdbId, item.type),
                title: item.title,
                year: item.releaseYear,
                poster: item.poster,
                subtitle: item.releaseYear ? `TV · ${item.releaseYear}` : 'TV',
              }}
            />
          ))}
        </div>
      </section>
    </div>
  )
}
