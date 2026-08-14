import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { getById } from '../data/catalog'
import {
  mediaKey,
  parseMediaKey,
  raceSources,
  resolveTitleFromPath,
  watchUrl,
  type LabDetails,
} from '../api/lab'
import { EpisodeCarousel } from '../components/EpisodeCarousel'
import { usePlaybackStore } from '../stores/playback'

export function MediaPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const catalogItem = id ? getById(id) : undefined
  const parsed = id ? parseMediaKey(id) : null

  const [remote, setRemote] = useState<LabDetails | null>(null)
  const [season, setSeason] = useState(1)
  const [episode, setEpisode] = useState(1)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')

  const setTitle = usePlaybackStore((s) => s.setTitle)
  const resetStreams = usePlaybackStore((s) => s.resetStreams)
  const addStream = usePlaybackStore((s) => s.addStream)
  const setRaceProgress = usePlaybackStore((s) => s.setRaceProgress)
  const streams = usePlaybackStore((s) => s.streams)
  const raceTried = usePlaybackStore((s) => s.raceTried)
  const raceTotal = usePlaybackStore((s) => s.raceTotal)
  const racing = usePlaybackStore((s) => s.racing)

  useEffect(() => {
    if (!parsed || !id) {
      setRemote(null)
      return
    }
    let cancelled = false
    resolveTitleFromPath(id)
      .then((hit) => {
        if (!cancelled) setRemote(hit)
      })
      .catch(() => {
        if (!cancelled) {
          setRemote({
            tmdbId: parsed.tmdbId,
            type: parsed.type,
            title: `${parsed.type === 'show' ? 'Show' : 'Movie'} ${parsed.tmdbId}`,
            releaseYear: null,
            overview: 'Could not load TMDB details. Lab API may be offline.',
            poster: null,
            backdrop: null,
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [id, parsed?.type, parsed?.tmdbId])

  const view = useMemo(() => {
    if (catalogItem) {
      return {
        kind: 'catalog' as const,
        id: catalogItem.id,
        type: catalogItem.type,
        title: catalogItem.title,
        year: catalogItem.year,
        overview: catalogItem.overview,
        poster: catalogItem.poster,
        backdrop: catalogItem.backdrop,
        meta: `${catalogItem.year}${catalogItem.runtimeMinutes ? ` · ${catalogItem.runtimeMinutes} min` : ''} · ${catalogItem.genres.join(', ')}`,
      }
    }
    if (parsed && remote) {
      const pathId = mediaKey(remote.title, remote.tmdbId, remote.type)
      return {
        kind: 'tmdb' as const,
        id: pathId,
        type: remote.type,
        tmdbId: remote.tmdbId,
        title: remote.title,
        year: remote.releaseYear,
        overview: remote.overview,
        poster: remote.poster,
        backdrop: remote.backdrop || remote.poster,
        meta: `${remote.type === 'show' ? 'TV' : 'Movie'}${remote.releaseYear ? ` · ${remote.releaseYear}` : ''} · TMDB ${remote.tmdbId}`,
      }
    }
    return null
  }, [catalogItem, parsed, remote])

  // Canonicalize /media/legacy → /media/Title-Slug-ID
  useEffect(() => {
    if (!id || !view || view.kind !== 'tmdb') return
    if (id !== view.id) {
      navigate(`/media/${view.id}`, { replace: true })
    }
  }, [id, view, navigate])

  if (!id || (!catalogItem && !parsed)) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-20 text-center md:px-6">
        <h1 className="text-xl font-semibold">Not found</h1>
        <Link to="/" className="mt-4 inline-block text-accent hover:text-accent-hover">
          Back home
        </Link>
      </div>
    )
  }

  if (!view) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-20 text-center text-text-muted md:px-6">
        Loading title…
      </div>
    )
  }

  const startRaceAndWatch = async (party = false) => {
    if (view.kind === 'catalog') {
      navigate(watchUrl(view.id, { party }))
      return
    }

    setBusy(true)
    resetStreams()
    setTitle({
      id: view.id,
      type: view.type,
      tmdbId: view.tmdbId,
      title: view.title,
      year: view.year,
      overview: view.overview,
      poster: view.poster,
      backdrop: view.backdrop,
      season: view.type === 'show' ? season : undefined,
      episode: view.type === 'show' ? episode : undefined,
    })
    setRaceProgress({
      racing: true,
      raceTried: 0,
      raceTotal: 0,
      raceMessage: 'Racing providers…',
    })
    setStatus('Racing providers for the first stream…')

    // Watch party: go to player immediately so host UI / invite link appear
    if (party) {
      navigate(watchUrl(view.id, { party: true }))
    }

    let navigated = party
    try {
      await raceSources(
        {
          type: view.type,
          tmdbId: view.tmdbId,
          title: view.title,
          releaseYear: view.year ?? undefined,
          season,
          episode,
        },
        {
          onStart: (data) => {
            setRaceProgress({ raceTotal: data.total, raceMessage: `0 / ${data.total}` })
          },
          onProgress: (data) => {
            setRaceProgress({
              raceTried: data.tried,
              raceTotal: data.total,
              raceMessage: `${data.tried} / ${data.total} · ${data.name}`,
            })
            setStatus(`Tried ${data.tried}/${data.total} — ${data.name}`)
          },
          onStream: (stream) => {
            addStream(stream)
            if (!navigated) {
              navigated = true
              navigate(watchUrl(view.id, { party }))
            }
          },
          onDone: (data) => {
            setRaceProgress({
              racing: false,
              raceMessage: `${data.playableCount} playable · ${data.ms}ms`,
            })
            if (!navigated) {
              setStatus(`No playable streams after ${data.total} sources.`)
            } else {
              setStatus(`Done — ${data.playableCount} stream(s).`)
            }
          },
          onError: (message) => setStatus(message),
        },
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 md:px-6">
      <div className="relative overflow-hidden rounded-2xl border border-border">
        {view.backdrop ? (
          <img
            src={view.backdrop}
            alt=""
            className="absolute inset-0 h-full w-full object-cover opacity-30"
          />
        ) : null}
        <div className="relative flex flex-col gap-6 bg-gradient-to-t from-bg via-bg/90 to-bg/40 p-6 md:flex-row md:p-10">
          {view.poster ? (
            <img
              src={view.poster}
              alt=""
              className="h-64 w-44 shrink-0 rounded-xl object-cover shadow-lg md:h-80 md:w-52"
            />
          ) : (
            <div className="flex h-64 w-44 shrink-0 items-center justify-center rounded-xl bg-bg-elevated text-text-muted md:h-80 md:w-52">
              No poster
            </div>
          )}
          <div className="flex min-w-0 flex-1 flex-col">
            <p className="text-xs uppercase tracking-wider text-text-muted">{view.meta}</p>
            <h1 className="mt-1 text-3xl font-semibold tracking-tight md:text-4xl">{view.title}</h1>
            <p className="mt-4 max-w-2xl text-sm leading-relaxed text-text-muted md:text-base">
              {view.overview || 'No overview.'}
            </p>

            {view.type === 'show' && view.kind === 'tmdb' ? (
              <div className="demo-media-episodes mt-5 w-full max-w-3xl">
                <EpisodeCarousel
                  tmdbId={view.tmdbId}
                  seasons={remote?.seasons || []}
                  season={season}
                  episode={episode}
                  onSelect={(s, e) => {
                    setSeason(s)
                    setEpisode(e)
                  }}
                  variant="list"
                />
              </div>
            ) : null}

            <div className="mt-6 flex flex-wrap gap-3">
              <button
                type="button"
                disabled={busy || racing}
                onClick={() => void startRaceAndWatch(false)}
                className="rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-white hover:bg-accent-hover disabled:opacity-50"
              >
                {busy || racing ? 'Finding stream…' : 'Play'}
              </button>
              <button
                type="button"
                disabled={busy || racing}
                onClick={() => void startRaceAndWatch(true)}
                className="rounded-lg border border-border bg-bg-elevated px-5 py-2.5 text-sm font-semibold hover:border-accent/50"
              >
                Watch party
              </button>
            </div>

            {status || racing ? (
              <p className="mt-4 text-sm text-text-muted">
                {status}
                {racing && raceTotal > 0 ? ` (${raceTried}/${raceTotal})` : ''}
                {streams.length > 0 ? ` · ${streams.length} stream(s)` : ''}
              </p>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  )
}
