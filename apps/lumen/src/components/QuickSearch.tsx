import { useCallback, useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { cacheTitle, mediaKey, searchLab, type LabSearchHit } from '../api/lab'
import { searchCatalog, type CatalogItem } from '../data/catalog'

type PreviewItem =
  | { kind: 'local'; item: CatalogItem }
  | { kind: 'remote'; item: LabSearchHit }

const DEBOUNCE_MS = 220
const MAX_REMOTE = 6
const MAX_LOCAL = 3

function mediaPath(hit: PreviewItem): string {
  if (hit.kind === 'local') return `/media/${hit.item.id}`
  return `/media/${mediaKey(hit.item.title, hit.item.tmdbId, hit.item.type)}`
}

export function QuickSearch() {
  const navigate = useNavigate()
  const listId = useId()
  const rootRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [remote, setRemote] = useState<LabSearchHit[]>([])
  const [local, setLocal] = useState<CatalogItem[]>([])
  const [active, setActive] = useState(0)

  const items: PreviewItem[] = [
    ...local.slice(0, MAX_LOCAL).map((item) => ({ kind: 'local' as const, item })),
    ...remote.slice(0, MAX_REMOTE).map((item) => ({ kind: 'remote' as const, item })),
  ]

  const close = useCallback(() => {
    setOpen(false)
    setActive(0)
  }, [])

  // Debounced fetch
  useEffect(() => {
    const query = q.trim()
    if (query.length < 1) {
      setRemote([])
      setLocal([])
      setError('')
      setLoading(false)
      return
    }

    setLocal(searchCatalog(query))
    setLoading(true)
    setError('')

    let cancelled = false
    const timer = window.setTimeout(() => {
      searchLab(query)
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
    }, DEBOUNCE_MS)

    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [q])

  // Click outside
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

  const selectItem = (hit: PreviewItem) => {
    if (hit.kind === 'remote') cacheTitle(hit.item)
    close()
    setQ('')
    navigate(mediaPath(hit))
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
    <div ref={rootRef} className="relative ml-auto min-w-0 flex-1 max-w-md">
      <form onSubmit={onSubmit} className="relative">
        <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-dim">
          <SearchIcon />
        </span>
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
          placeholder="Search movies & TV…"
          role="combobox"
          aria-expanded={showPanel}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={
            showPanel && items[active] ? `${listId}-opt-${active}` : undefined
          }
          className="w-full rounded-xl border border-white/5 bg-bg-pill py-2 pl-10 pr-3 text-sm text-white placeholder:text-text-dim outline-none ring-accent/40 focus:ring-2"
          autoComplete="off"
          spellCheck={false}
        />
        {loading && showPanel ? (
          <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[10px] uppercase tracking-wide text-text-dim">
            …
          </span>
        ) : null}
      </form>

      {showPanel ? (
        <div
          id={listId}
          role="listbox"
          className="absolute left-0 right-0 top-[calc(100%+0.4rem)] z-[80] overflow-hidden rounded-2xl border border-white/10 bg-bg-elevated/95 shadow-2xl shadow-black/60 backdrop-blur-md"
        >
          {error && items.length === 0 ? (
            <p className="px-4 py-3 text-sm text-danger">{error}</p>
          ) : null}

          {items.length === 0 && !loading ? (
            <p className="px-4 py-6 text-center text-sm text-text-muted">
              No matches for “{q.trim()}”
            </p>
          ) : null}

          {items.length > 0 ? (
            <ul className="max-h-[min(70vh,22rem)] overflow-y-auto py-1">
              {items.map((hit, index) => {
                const title = hit.kind === 'local' ? hit.item.title : hit.item.title
                const poster = hit.kind === 'local' ? hit.item.poster : hit.item.poster
                const meta =
                  hit.kind === 'local'
                    ? `Demo · ${hit.item.year}${hit.item.runtimeMinutes ? ` · ${hit.item.runtimeMinutes}m` : ''}`
                    : `${hit.item.type === 'show' ? 'TV' : 'Movie'}${
                        hit.item.releaseYear ? ` · ${hit.item.releaseYear}` : ''
                      }`
                const selected = index === active
                return (
                  <li key={`${hit.kind}-${mediaPath(hit)}-${index}`} role="presentation">
                    <button
                      type="button"
                      id={`${listId}-opt-${index}`}
                      role="option"
                      aria-selected={selected}
                      onMouseEnter={() => setActive(index)}
                      onClick={() => selectItem(hit)}
                      className={[
                        'flex w-full items-center gap-3 px-3 py-2 text-left transition',
                        selected ? 'bg-white/10' : 'hover:bg-white/5',
                      ].join(' ')}
                    >
                      <div className="h-14 w-10 shrink-0 overflow-hidden rounded-md bg-bg-hover">
                        {poster ? (
                          <img src={poster} alt="" className="h-full w-full object-cover" />
                        ) : (
                          <div className="flex h-full w-full items-center justify-center text-[10px] text-text-dim">
                            —
                          </div>
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-semibold text-white">{title}</div>
                        <div className="truncate text-xs text-text-muted">{meta}</div>
                      </div>
                      {hit.kind === 'local' ? (
                        <span className="shrink-0 rounded bg-white/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-text-dim">
                          Local
                        </span>
                      ) : null}
                    </button>
                  </li>
                )
              })}
            </ul>
          ) : null}

          <button
            type="button"
            onClick={goFullSearch}
            className="flex w-full items-center justify-between border-t border-white/10 bg-bg-pill/80 px-4 py-2.5 text-left text-xs font-medium text-accent transition hover:bg-white/5"
          >
            <span>
              {loading ? 'Searching…' : `See all results for “${q.trim()}”`}
            </span>
            <span className="text-text-dim">Enter ↵</span>
          </button>
        </div>
      ) : null}
    </div>
  )
}

function SearchIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16Z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <path
        d="M21 21l-4.3-4.3"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  )
}
