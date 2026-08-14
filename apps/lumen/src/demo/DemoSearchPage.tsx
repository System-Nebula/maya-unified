import { FormEvent, useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { cacheTitle, searchLab, type LabSearchHit } from '../api/lab'
import { useDemoDetails } from './DemoDetailsContext'

const DEBOUNCE_MS = 220

export function DemoSearchPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { openDetails } = useDemoDetails()
  const urlQ = params.get('q') || ''
  const [q, setQ] = useState(urlQ)
  const [results, setResults] = useState<LabSearchHit[]>([])
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  // Keep input in sync when URL changes from header / navigation
  useEffect(() => {
    setQ(urlQ)
  }, [urlQ])

  // Live: debounce typing into the URL (replace) like classic QuickSearch → search
  useEffect(() => {
    const next = q.trim()
    const current = urlQ.trim()
    if (next === current) return
    const timer = window.setTimeout(() => {
      navigate(next ? `/search?q=${encodeURIComponent(next)}` : '/search', {
        replace: true,
      })
    }, DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [q, urlQ, navigate])

  // Fetch when URL query settles
  useEffect(() => {
    if (!urlQ.trim()) {
      setResults([])
      setStatus('')
      setError('')
      setBusy(false)
      return
    }
    let cancelled = false
    setBusy(true)
    setError('')
    setStatus('Searching…')
    searchLab(urlQ.trim())
      .then((data) => {
        if (cancelled) return
        const hits = data.results || []
        hits.forEach((hit) => cacheTitle(hit))
        setResults(hits)
        setStatus(hits.length ? `${hits.length} result(s)` : 'No titles found')
        if (data.error) setError(data.error)
      })
      .catch((e: Error) => {
        if (!cancelled) {
          setResults([])
          setError(e.message)
          setStatus('')
        }
      })
      .finally(() => {
        if (!cancelled) setBusy(false)
      })
    return () => {
      cancelled = true
    }
  }, [urlQ])

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    const query = q.trim()
    navigate(query ? `/search?q=${encodeURIComponent(query)}` : '/search', {
      replace: true,
    })
  }

  return (
    <div className="demo-search-page">
      <h1 className="demo-display">Search</h1>
      <p className="demo-status" style={{ marginBottom: '1.25rem' }}>
        Find anything. Filter everything.
      </p>
      <form className="demo-search-form" onSubmit={onSubmit}>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Obsession, Spring Breakers…"
          autoFocus
          autoComplete="off"
          spellCheck={false}
        />
        <button type="submit" disabled={busy}>
          {busy ? '…' : 'Go'}
        </button>
      </form>
      {error ? <p className="demo-error">{error}</p> : null}
      {status ? <p className="demo-status">{status}</p> : null}
      <div>
        {results.map((hit) => (
          <button
            key={`${hit.type}-${hit.tmdbId}`}
            type="button"
            className="demo-result"
            onClick={() => {
              cacheTitle(hit)
              openDetails(hit)
            }}
          >
            {hit.poster ? (
              <img src={hit.poster} alt="" />
            ) : (
              <div className="demo-result-ph">No art</div>
            )}
            <div>
              <h2>{hit.title}</h2>
              <p>
                {hit.type === 'show' ? 'TV' : 'Movie'}
                {hit.releaseYear ? ` · ${hit.releaseYear}` : ''}
                {hit.overview ? ` — ${hit.overview}` : ''}
              </p>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
