import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { cacheTitle, mediaKey, searchLab, type LabSearchHit } from '../api/lab'
import { searchCatalog } from '../data/catalog'
import { MediaCard } from '../components/MediaCard'

export function SearchPage() {
  const [params] = useSearchParams()
  const q = params.get('q') ?? ''
  const local = useMemo(() => searchCatalog(q), [q])
  const [remote, setRemote] = useState<LabSearchHit[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!q.trim()) {
      setRemote([])
      setError('')
      return
    }
    let cancelled = false
    setLoading(true)
    setError('')
    searchLab(q.trim())
      .then((data) => {
        if (cancelled) return
        if (data.error && !data.results?.length) {
          setError(data.error)
          setRemote([])
          return
        }
        const results = data.results || []
        results.forEach((hit) => cacheTitle(hit))
        setRemote(results)
      })
      .catch((e: Error) => {
        if (!cancelled) {
          setError(e.message)
          setRemote([])
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [q])

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 md:px-6">
      <h1 className="text-2xl font-bold">{q ? `Results for “${q}”` : 'Library'}</h1>
      <p className="mt-1 text-sm text-text-muted">
        {q
          ? loading
            ? 'Searching TMDB…'
            : `${remote.length} TMDB · ${local.length} local demo`
          : `${local.length} local demo title${local.length === 1 ? '' : 's'}`}
      </p>
      {error ? <p className="mt-3 text-sm text-danger">{error}</p> : null}

      {q && remote.length > 0 ? (
        <section className="mt-8">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-text-dim">
            Movies & TV
          </h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
            {remote.map((hit) => (
              <MediaCard
                key={`${hit.type}-${hit.tmdbId}`}
                item={{
                  id: mediaKey(hit.title, hit.tmdbId, hit.type),
                  title: hit.title,
                  year: hit.releaseYear,
                  poster: hit.poster,
                  subtitle: `${hit.type === 'show' ? 'TV' : 'Movie'}${hit.releaseYear ? ` · ${hit.releaseYear}` : ''}`,
                }}
              />
            ))}
          </div>
        </section>
      ) : null}

      <section className="mt-10">
        {q ? (
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-text-dim">
            Local demos
          </h2>
        ) : null}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
          {local.map((item) => (
            <MediaCard
              key={item.id}
              item={{
                id: item.id,
                title: item.title,
                year: item.year,
                poster: item.poster,
                subtitle: item.runtimeMinutes ? `${item.year} · ${item.runtimeMinutes}m` : String(item.year),
              }}
            />
          ))}
        </div>
      </section>

      {q && !loading && remote.length === 0 && local.length === 0 ? (
        <p className="mt-12 text-center text-text-muted">Nothing matched. Try another search.</p>
      ) : null}
    </div>
  )
}
