import { useEffect, useRef, useState } from 'react'
import { fetchSeason, type LabEpisodeInfo, type LabSeasonInfo } from '../api/lab'

type Props = {
  tmdbId: string
  seasons: LabSeasonInfo[]
  season: number
  episode: number
  onSelect: (season: number, episode: number) => void
  /** menu = player overlay; rail = horizontal watch rail; list = Netflix-style details */
  variant?: 'menu' | 'rail' | 'list'
}

function formatRuntime(minutes?: number | null): string | null {
  if (!minutes || minutes < 1) return null
  return `${minutes}m`
}

export function EpisodeCarousel({
  tmdbId,
  seasons,
  season,
  episode,
  onSelect,
  variant = 'menu',
}: Props) {
  const scrollerRef = useRef<HTMLDivElement>(null)
  const [seasonNumber, setSeasonNumber] = useState(season)
  const [episodes, setEpisodes] = useState<LabEpisodeInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [error, setError] = useState('')

  const seasonList = seasons
    .filter((s) => s.seasonNumber > 0 && s.episodeCount > 0)
    .sort((a, b) => a.seasonNumber - b.seasonNumber)

  const seasonOptions =
    seasonList.length > 0
      ? seasonList
      : [{ seasonNumber, episodeCount: episodes.length || 1, name: `Season ${seasonNumber}` }]

  useEffect(() => {
    setSeasonNumber(season)
  }, [season])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    fetchSeason(tmdbId, seasonNumber)
      .then((data) => {
        if (cancelled) return
        setEpisodes(data.episodes || [])
      })
      .catch((e) => {
        if (cancelled) return
        setEpisodes([])
        setError(e instanceof Error ? e.message : 'Failed to load episodes')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [tmdbId, seasonNumber])

  useEffect(() => {
    const root = scrollerRef.current
    if (!root) return
    const active = root.querySelector<HTMLElement>('[data-active="true"]')
    active?.scrollIntoView({
      inline: variant === 'list' ? 'nearest' : 'center',
      block: 'nearest',
      behavior: 'smooth',
    })
  }, [episodes, episode, seasonNumber, variant])

  const scrollBy = (dir: -1 | 1) => {
    const root = scrollerRef.current
    if (!root) return
    root.scrollBy({ left: dir * Math.max(280, root.clientWidth * 0.7), behavior: 'smooth' })
  }

  const seasonMeta = seasonOptions.find((s) => s.seasonNumber === seasonNumber)

  if (variant === 'list') {
    return (
      <div className="ep-carousel is-list">
        <div className="ep-list-head">
          <h3 className="ep-list-title">Episodes</h3>
          {seasonOptions.length > 0 ? (
            <label className="ep-list-season">
              <select
                value={seasonNumber}
                onChange={(e) => setSeasonNumber(Number(e.target.value))}
                aria-label="Season"
              >
                {seasonOptions.map((s) => (
                  <option key={s.seasonNumber} value={s.seasonNumber}>
                    {s.name || `Season ${s.seasonNumber}`}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <span className="ep-list-season-static">
              {seasonMeta?.name || `Season ${seasonNumber}`}
            </span>
          )}
        </div>

        {error ? <p className="ep-carousel-empty">{error}</p> : null}
        {loading && !episodes.length ? <p className="ep-carousel-empty">Loading episodes…</p> : null}

        <div className="ep-list" ref={scrollerRef}>
          {episodes.map((ep) => {
            const active = ep.seasonNumber === season && ep.episodeNumber === episode
            const runtime = formatRuntime(ep.runtime)
            const overview = ep.overview?.trim() || 'No synopsis yet.'
            return (
              <button
                key={`${ep.seasonNumber}-${ep.episodeNumber}`}
                type="button"
                className={['ep-list-row', active ? 'is-active' : ''].filter(Boolean).join(' ')}
                data-active={active ? 'true' : undefined}
                onClick={() => onSelect(ep.seasonNumber, ep.episodeNumber)}
              >
                <span className="ep-list-num">{ep.episodeNumber}</span>
                <span className="ep-list-thumb" aria-hidden>
                  {ep.still ? (
                    <img src={ep.still} alt="" loading="lazy" />
                  ) : (
                    <span className="ep-card-still-fallback" />
                  )}
                </span>
                <span className="ep-list-body">
                  <span className="ep-list-topline">
                    <span className="ep-list-name">{ep.name}</span>
                    {runtime ? <span className="ep-list-runtime">{runtime}</span> : null}
                  </span>
                  <span className="ep-list-overview">{overview}</span>
                </span>
              </button>
            )
          })}
        </div>
      </div>
    )
  }

  return (
    <div className={['ep-carousel', variant === 'rail' ? 'is-rail' : 'is-menu'].join(' ')}>
      <div className="ep-carousel-head">
        <div className="ep-carousel-season">
          <label>
            <span className="ep-carousel-season-label">
              {seasonMeta?.name || `Season ${seasonNumber}`}
            </span>
            {seasonOptions.length > 1 ? (
              <select
                value={seasonNumber}
                onChange={(e) => setSeasonNumber(Number(e.target.value))}
                aria-label="Season"
              >
                {seasonOptions.map((s) => (
                  <option key={s.seasonNumber} value={s.seasonNumber}>
                    {s.name || `Season ${s.seasonNumber}`}
                  </option>
                ))}
              </select>
            ) : null}
          </label>
        </div>
        <div className="ep-carousel-nav">
          <button type="button" aria-label="Previous episodes" onClick={() => scrollBy(-1)}>
            ‹
          </button>
          <button type="button" aria-label="Next episodes" onClick={() => scrollBy(1)}>
            ›
          </button>
        </div>
      </div>

      {error ? <p className="ep-carousel-empty">{error}</p> : null}
      {loading && !episodes.length ? <p className="ep-carousel-empty">Loading episodes…</p> : null}

      <div className="ep-carousel-track" ref={scrollerRef}>
        {episodes.map((ep) => {
          const active = ep.seasonNumber === season && ep.episodeNumber === episode
          const open = expanded === ep.episodeNumber
          const overview = ep.overview?.trim() || 'No synopsis yet.'
          return (
            <article
              key={`${ep.seasonNumber}-${ep.episodeNumber}`}
              className={['ep-card', active ? 'is-active' : ''].filter(Boolean).join(' ')}
              data-active={active ? 'true' : undefined}
            >
              <button
                type="button"
                className="ep-card-media"
                onClick={() => onSelect(ep.seasonNumber, ep.episodeNumber)}
              >
                {ep.still ? (
                  <img src={ep.still} alt="" loading="lazy" />
                ) : (
                  <div className="ep-card-still-fallback" />
                )}
                <span className="ep-card-badge">E{ep.episodeNumber}</span>
                {active ? <span className="ep-card-progress" /> : null}
              </button>
              <div className="ep-card-body">
                <button
                  type="button"
                  className="ep-card-title"
                  onClick={() => onSelect(ep.seasonNumber, ep.episodeNumber)}
                >
                  {ep.name}
                </button>
                <p className={open ? 'ep-card-overview is-open' : 'ep-card-overview'}>{overview}</p>
                {overview.length > 90 ? (
                  <button
                    type="button"
                    className="ep-card-more"
                    onClick={() => setExpanded(open ? null : ep.episodeNumber)}
                  >
                    {open ? 'Show less' : 'Show more'}
                  </button>
                ) : null}
              </div>
            </article>
          )
        })}
      </div>
    </div>
  )
}
