import { useNavigate } from 'react-router-dom'
import { demoWatchUrl } from '../../api/lab'
import {
  formatResumeLabel,
  type WatchHistoryEntry,
} from '../../lib/watchHistory'
import { usePlaybackStore } from '../../stores/playback'

type Props = {
  id?: string
  title: string
  items: WatchHistoryEntry[]
  /** continue = in-progress; history = includes completed */
  variant?: 'continue' | 'history'
}

export function DemoWatchHistoryRail({
  id,
  title,
  items,
  variant = 'continue',
}: Props) {
  const navigate = useNavigate()
  const setTitle = usePlaybackStore((s) => s.setTitle)

  if (!items.length) return null

  return (
    <section className="demo-rail" id={id}>
      <h2 className="demo-rail-title">{title}</h2>
      <div className="demo-rail-fade" aria-hidden />
      <div className="demo-rail-track">
        {items.map((entry) => {
          const progress = Math.min(100, Math.max(2, entry.percent * 100))
          const label = formatResumeLabel(entry)
          return (
            <button
              key={entry.id}
              type="button"
              className="demo-poster demo-poster-continue"
              onClick={() => {
                setTitle({
                  id: entry.pathId,
                  type: entry.type,
                  tmdbId: entry.tmdbId,
                  title: entry.title,
                  year: entry.year,
                  overview: '',
                  poster: entry.poster,
                  backdrop: entry.backdrop,
                  season: entry.season,
                  episode: entry.episode,
                })
                navigate(demoWatchUrl(entry.pathId))
              }}
            >
              <div className="demo-poster-art">
                {entry.poster ? (
                  <img src={entry.poster} alt="" loading="lazy" />
                ) : (
                  <div className="demo-empty-poster">{entry.title}</div>
                )}
                {variant === 'continue' && !entry.completed ? (
                  <div className="demo-poster-progress" aria-hidden>
                    <span style={{ width: `${progress}%` }} />
                  </div>
                ) : null}
              </div>
              <div className="demo-poster-meta">
                <div className="demo-poster-title">{entry.title}</div>
                <div className="demo-poster-year">{label}</div>
              </div>
            </button>
          )
        })}
      </div>
    </section>
  )
}
