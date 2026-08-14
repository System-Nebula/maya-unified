import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from 'react'
import { useNavigate } from 'react-router-dom'
import { cacheTitle, searchLab, type LabSearchHit } from '../../api/lab'
import { useDemoDetails } from '../DemoDetailsContext'

const DEBOUNCE_MS = 220
const MAX_RESULTS = 8

export function DemoQuickSearch() {
  const navigate = useNavigate()
  const { openDetails } = useDemoDetails()
  const listId = useId()
  const rootRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [results, setResults] = useState<LabSearchHit[]>([])
  const [active, setActive] = useState(0)

  const items = results.slice(0, MAX_RESULTS)

  const close = useCallback(() => {
    setOpen(false)
    setActive(0)
  }, [])

  useEffect(() => {
    const query = q.trim()
    if (query.length < 1) {
      setResults([])
      setError('')
      setLoading(false)
      return
    }

    setLoading(true)
    setError('')

    let cancelled = false
    const timer = window.setTimeout(() => {
      searchLab(query)
        .then((data) => {
          if (cancelled) return
          if (data.error && !data.results?.length) {
            setError(data.error)
            setResults([])
            return
          }
          const hits = data.results || []
          hits.forEach((hit) => cacheTitle(hit))
          setResults(hits)
        })
        .catch((e: Error) => {
          if (!cancelled) {
            setError(e.message)
            setResults([])
          }
        })
        .finally(() => {
          if (!cancelled) setLoading(false)
        })
    }, DEBOUNCE_MS)

    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [q])

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) close()
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open, close])

  const goFullSearch = () => {
    const query = q.trim()
    close()
    navigate(query ? `/search?q=${encodeURIComponent(query)}` : '/search')
  }

  const selectItem = (hit: LabSearchHit) => {
    cacheTitle(hit)
    close()
    setQ('')
    openDetails(hit)
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (open && items[active]) {
      selectItem(items[active])
      return
    }
    goFullSearch()
  }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      close()
      inputRef.current?.blur()
      return
    }
    if (!open || items.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => (i + 1) % items.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => (i - 1 + items.length) % items.length)
    }
  }

  const showPanel = open && q.trim().length > 0

  return (
    <div ref={rootRef} className="demo-quick-search">
      <form onSubmit={onSubmit} className="demo-quick-search-form">
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => {
            setQ(e.target.value)
            setOpen(true)
            setActive(0)
          }}
          onFocus={() => {
            if (q.trim()) setOpen(true)
          }}
          onKeyDown={onKeyDown}
          placeholder="Search titles…"
          role="combobox"
          aria-expanded={showPanel}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={
            showPanel && items[active] ? `${listId}-opt-${active}` : undefined
          }
          autoComplete="off"
          spellCheck={false}
        />
        {loading && showPanel ? <span className="demo-quick-search-busy">…</span> : null}
      </form>

      {showPanel ? (
        <div id={listId} role="listbox" className="demo-quick-search-panel">
          {error && items.length === 0 ? <p className="demo-quick-search-msg demo-error">{error}</p> : null}

          {items.length === 0 && !loading ? (
            <p className="demo-quick-search-msg">No matches for “{q.trim()}”</p>
          ) : null}

          {items.length > 0 ? (
            <ul>
              {items.map((hit, index) => {
                const selected = index === active
                return (
                  <li key={`${hit.type}-${hit.tmdbId}`} role="presentation">
                    <button
                      type="button"
                      id={`${listId}-opt-${index}`}
                      role="option"
                      aria-selected={selected}
                      className={selected ? 'is-active' : undefined}
                      onMouseEnter={() => setActive(index)}
                      onClick={() => selectItem(hit)}
                    >
                      {hit.poster ? (
                        <img src={hit.poster} alt="" />
                      ) : (
                        <span className="demo-quick-search-ph">—</span>
                      )}
                      <span className="demo-quick-search-meta">
                        <span className="demo-quick-search-title">{hit.title}</span>
                        <span>
                          {hit.type === 'show' ? 'TV' : 'Movie'}
                          {hit.releaseYear ? ` · ${hit.releaseYear}` : ''}
                        </span>
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          ) : null}

          <button type="button" className="demo-quick-search-all" onClick={goFullSearch}>
            <span>{loading ? 'Searching…' : `See all results for “${q.trim()}”`}</span>
            <span>Enter ↵</span>
          </button>
        </div>
      ) : null}
    </div>
  )
}
