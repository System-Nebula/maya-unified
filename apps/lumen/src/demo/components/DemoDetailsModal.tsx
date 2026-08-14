import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getById } from '../../data/catalog'
import {
  demoWatchUrl,
  mediaKey,
  parseMediaKey,
  raceSources,
  resolveTitleFromPath,
  type LabDetails,
} from '../../api/lab'
import { AudioModeToggle } from '../../components/AudioModeToggle'
import { EpisodeCarousel } from '../../components/EpisodeCarousel'
import {
  readAudioMode,
  shouldShowAudioModeToggle,
  saveAudioMode,
  type AudioMode,
} from '../../lib/audioMode'
import { getLatestForTitle } from '../../lib/watchHistory'
import { usePlaybackStore } from '../../stores/playback'
import { useDemoDetails } from '../DemoDetailsContext'

export function DemoDetailsModal() {
  const navigate = useNavigate()
  const { detailsId, seed, autoWatch, autoParty, closeDetails, clearAutoWatch } = useDemoDetails()

  const catalogItem = detailsId ? getById(detailsId) : undefined
  const parsed = detailsId ? parseMediaKey(detailsId) : null

  const [remote, setRemote] = useState<LabDetails | null>(null)
  const [season, setSeason] = useState(1)
  const [episode, setEpisode] = useState(1)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [audioMode, setAudioMode] = useState<AudioMode>(() => readAudioMode())
  const [resumeLabel, setResumeLabel] = useState<string | null>(null)

  const setTitle = usePlaybackStore((s) => s.setTitle)
  const resetStreams = usePlaybackStore((s) => s.resetStreams)
  const addStream = usePlaybackStore((s) => s.addStream)
  const setRaceProgress = usePlaybackStore((s) => s.setRaceProgress)
  const streams = usePlaybackStore((s) => s.streams)
  const raceTried = usePlaybackStore((s) => s.raceTried)
  const raceTotal = usePlaybackStore((s) => s.raceTotal)
  const racing = usePlaybackStore((s) => s.racing)

  useEffect(() => {
    if (!detailsId) return
    setStatus('')
    setSeason(1)
    setEpisode(1)
    setBusy(false)
    setResumeLabel(null)
    const parsedKey = parseMediaKey(detailsId)
    if (parsedKey) {
      void getLatestForTitle(parsedKey.type, parsedKey.tmdbId)
        .then((saved) => {
          if (!saved) return
          if (saved.season) setSeason(saved.season)
          if (saved.episode) setEpisode(saved.episode)
          if (!saved.completed && saved.currentTime >= 20) {
            setResumeLabel(
              saved.type === 'show'
                ? `Resume S${saved.season}E${saved.episode}`
                : 'Resume',
            )
          }
        })
        .catch(() => {})
    }
  }, [detailsId])

  useEffect(() => {
    if (!detailsId || !parsed) {
      setRemote(null)
      return
    }
    if (seed && mediaKey(seed.title, seed.tmdbId, seed.type) === detailsId) {
      setRemote({
        ...seed,
        overview: seed.overview || '',
        backdrop: 'backdrop' in seed ? seed.backdrop || null : null,
      })
    }
    let cancelled = false
    resolveTitleFromPath(detailsId)
      .then((hit) => {
        if (!cancelled && hit) setRemote(hit)
      })
      .catch(() => {
        if (!cancelled && !seed) {
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
  }, [detailsId, parsed?.type, parsed?.tmdbId, seed])

  useEffect(() => {
    if (!detailsId) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeDetails()
    }
    document.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [detailsId, closeDetails])

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
        meta: `${remote.type === 'show' ? 'TV' : 'Movie'}${remote.releaseYear ? ` · ${remote.releaseYear}` : ''}`,
      }
    }
    return null
  }, [catalogItem, parsed, remote])

  const startRaceAndWatch = async (party = false) => {
    if (!view) return
    if (view.kind === 'catalog') {
      closeDetails()
      navigate(demoWatchUrl(view.id, { party }))
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
      isAnime: remote?.isAnime,
    })
    setRaceProgress({
      racing: true,
      raceTried: 0,
      raceTotal: 0,
      raceMessage: 'Racing providers…',
    })
    setStatus('Racing providers for the first stream…')

    if (party) {
      closeDetails()
      navigate(demoWatchUrl(view.id, { party: true }))
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
              closeDetails()
              navigate(demoWatchUrl(view.id, { party }))
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

  useEffect(() => {
    if (!detailsId || !view || !autoWatch) return
    clearAutoWatch()
    void startRaceAndWatch(autoParty)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detailsId, view?.id, autoWatch, autoParty])

  if (!detailsId) return null

  const art = view?.backdrop || view?.poster || null

  return (
    <div className="demo-details-root" role="dialog" aria-modal="true" aria-label="Title details">
      <button type="button" className="demo-details-backdrop" aria-label="Close details" onClick={closeDetails} />
      <div className="demo-details-panel">
        <div className="demo-details-art" aria-hidden>
          {art ? <img src={art} alt="" /> : null}
          <div className="demo-details-scrim" />
        </div>

        <div className="demo-details-body">
          <button type="button" className="demo-details-close" onClick={closeDetails}>
            Close
          </button>

          <div className="demo-details-content">
            {!view ? (
              <p className="demo-status">Loading title…</p>
            ) : (
              <div className="demo-details-layout">
                <div className="demo-media-poster">
                  {view.poster ? (
                    <img src={view.poster} alt="" />
                  ) : (
                    <div className="demo-media-poster-ph">No poster</div>
                  )}
                </div>
                <div className="demo-media-copy">
                  <p className="demo-media-meta">{view.meta}</p>
                  <h2 className="demo-display demo-media-title">{view.title}</h2>
                  <p className="demo-media-overview">{view.overview || 'No overview.'}</p>

                  {view.type === 'show' && view.kind === 'tmdb' ? (
                    <div className="demo-media-episodes">
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

                  {shouldShowAudioModeToggle(remote?.originalLanguage) ? (
                    <AudioModeToggle
                      value={audioMode}
                      onChange={(mode) => {
                        setAudioMode(mode)
                        saveAudioMode(mode)
                      }}
                    />
                  ) : null}

                  <div className="demo-hero-ctas">
                    <button
                      type="button"
                      className="demo-btn demo-btn-primary"
                      disabled={busy || racing}
                      onClick={() => void startRaceAndWatch(false)}
                    >
                      {busy || racing ? 'Finding stream…' : resumeLabel || 'Watch'}
                    </button>
                    <button
                      type="button"
                      className="demo-btn demo-btn-ghost"
                      disabled={busy || racing}
                      onClick={() => void startRaceAndWatch(true)}
                    >
                      Watch party
                    </button>
                  </div>

                  {status || racing ? (
                    <p className="demo-media-status">
                      {status}
                      {racing && raceTotal > 0 ? ` (${raceTried}/${raceTotal})` : ''}
                      {streams.length > 0 ? ` · ${streams.length} stream(s)` : ''}
                    </p>
                  ) : null}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
