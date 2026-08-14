import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { getById } from '../data/catalog'
import {
  cacheTitle,
  fetchDetails,
  getCachedTitle,
  lookupPartyRoom,
  mediaKey,
  fetchSeason,
  nextEpisodeInSeries,
  parseMediaKey,
  partyRoomParam,
  raceSources,
  resolveNextEpisode,
  resolveTitleFromPath,
  streamIdentity,
  watchUrl,
  type LabEpisodeInfo,
  type LabSeasonInfo,
  type LabStream,
} from '../api/lab'

const AUTO_NEXT_KEY = 'cinemaya:auto-next'
const AUTO_PLAY_KEY = 'cinemaya:autoplay'
const AUTO_NEXT_SECONDS = 6

function readAutoNext(): boolean {
  try {
    const v = localStorage.getItem(AUTO_NEXT_KEY)
    if (v === '0') return false
    if (v === '1') return true
  } catch {
    /* ignore */
  }
  return true
}

function saveAutoNext(on: boolean) {
  try {
    localStorage.setItem(AUTO_NEXT_KEY, on ? '1' : '0')
  } catch {
    /* ignore */
  }
}

function readAutoPlay(): boolean {
  try {
    const v = localStorage.getItem(AUTO_PLAY_KEY)
    if (v === '0') return false
    if (v === '1') return true
  } catch {
    /* ignore */
  }
  return true
}

function saveAutoPlay(on: boolean) {
  try {
    localStorage.setItem(AUTO_PLAY_KEY, on ? '1' : '0')
  } catch {
    /* ignore */
  }
}
import { streamKindOf, usePlaybackStore } from '../stores/playback'
import { AudioModeToggle } from '../components/AudioModeToggle'
import { EpisodeCarousel } from '../components/EpisodeCarousel'
import {
  pickStreamIndex,
  readAudioMode,
  shouldShowAudioModeToggle,
  filterStreamsByAudio,
  formatStreamLabel,
  resolveAudioMode,
  nextFailoverStreamIndex,
  saveAudioMode,
  type AudioMode,
} from '../lib/audioMode'
import { VideoPlayer, type VideoPlayerHandle } from '../components/VideoPlayer'
import { PartyDock } from '../components/PartyDock'
import { PartyChat } from '../components/PartyChat'
import { PartyPanel } from '../components/PartyPanel'
import { NicknameGate } from '../components/NicknameGate'
import { usePartySync } from '../hooks/usePartySync'
import { usePartyStore } from '../stores/party'
import {
  getWatchProgress,
  upsertWatchProgress,
} from '../lib/watchHistory'

interface WatchPageProps {
  /** cinema = CINEMAYA skin (default); classic kept for legacy props */
  variant?: 'classic' | 'cinema'
}

export function WatchPage({ variant = 'cinema' }: WatchPageProps) {
  const { id } = useParams()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const catalogItem = id ? getById(id) : undefined
  const parsed = id ? parseMediaKey(id) : undefined
  const cinema = variant !== 'classic'
  const watchBase = '/watch'
  const mediaBase = '/media'

  const title = usePlaybackStore((s) => s.title)
  const streams = usePlaybackStore((s) => s.streams)
  const activeIndex = usePlaybackStore((s) => s.activeIndex)
  const setActiveIndex = usePlaybackStore((s) => s.setActiveIndex)
  const addStream = usePlaybackStore((s) => s.addStream)
  const resetStreams = usePlaybackStore((s) => s.resetStreams)
  const setTitle = usePlaybackStore((s) => s.setTitle)
  const setRaceProgress = usePlaybackStore((s) => s.setRaceProgress)
  const raceMessage = usePlaybackStore((s) => s.raceMessage)
  const racing = usePlaybackStore((s) => s.racing)

  const playerRef = useRef<VideoPlayerHandle>(null)
  const raceAbortRef = useRef<AbortController | null>(null)
  const fatalAtRef = useRef(0)
  const resumeDoneRef = useRef('')
  const lastSavedAtRef = useRef(0)
  const [audioMode, setAudioMode] = useState<AudioMode>(() => readAudioMode())
  const [autoNext, setAutoNext] = useState(() => readAutoNext())
  const [autoPlay, setAutoPlay] = useState(() => readAutoPlay())
  const [originalLanguage, setOriginalLanguage] = useState<string | null>(() =>
    parsed?.tmdbId ? getCachedTitle(parsed.tmdbId, parsed.type)?.originalLanguage || null : null,
  )
  const [seasons, setSeasons] = useState<LabSeasonInfo[]>([])
  const [seasonEpisodes, setSeasonEpisodes] = useState<LabEpisodeInfo[]>([])
  const [nextUp, setNextUp] = useState<{
    season: number
    episode: number
    seconds: number
  } | null>(null)
  const [status, setStatus] = useState('')
  const [invitePreview, setInvitePreview] = useState<{
    title?: string | null
    hostName?: string | null
  }>({})

  const enabled = usePartyStore((s) => s.enabled)
  const roomCode = usePartyStore((s) => s.roomCode)
  const role = usePartyStore((s) => s.role)
  const showOverlay = usePartyStore((s) => s.showOverlay)
  const peers = usePartyStore((s) => s.peers)
  const partyHostStream = usePartyStore((s) => s.hostStream)
  const setHostStream = usePartyStore((s) => s.setHostStream)
  const setSelfReady = usePartyStore((s) => s.setSelfReady)
  const selfReady = usePartyStore((s) => s.selfReady)
  const partyUserId = usePartyStore((s) => s.userId)
  const enableAsGuest = usePartyStore((s) => s.enableAsGuest)
  const setContentId = usePartyStore((s) => s.setContentId)
  const pendingInvite = usePartyStore((s) => s.pendingInvite)
  const nicknameNeeded = usePartyStore((s) => s.nicknameNeeded)
  const setPendingInvite = usePartyStore((s) => s.setPendingInvite)
  const setNicknameNeeded = usePartyStore((s) => s.setNicknameNeeded)
  const setDisplayName = usePartyStore((s) => s.setDisplayName)
  const panelOpen = usePartyStore((s) => s.panelOpen)
  const setPanelOpen = usePartyStore((s) => s.setPanelOpen)
  const enableAsHost = usePartyStore((s) => s.enableAsHost)

  const displayTitle =
    catalogItem?.title ||
    (title && (title.id === id || title.tmdbId === parsed?.tmdbId) ? title.title : null) ||
    (parsed ? `TMDB ${parsed.tmdbId}` : 'Unknown')

  const episodeLabel =
    parsed?.type === 'show' && title?.id === id && title.season && title.episode
      ? `S${title.season}E${title.episode}`
      : parsed?.type === 'show'
        ? 'S1E1'
        : null

  const watchHeading = episodeLabel ? `${displayTitle} · ${episodeLabel}` : displayTitle

  // TMDB language (for Sub/Dub toggle) + season counts for auto-next
  useEffect(() => {
    setNextUp(null)
    if (!parsed) {
      setSeasons([])
      setSeasonEpisodes([])
      setOriginalLanguage(null)
      return
    }
    const cachedLang = getCachedTitle(parsed.tmdbId, parsed.type)?.originalLanguage || null
    setOriginalLanguage(cachedLang)
    if (parsed.type !== 'show') {
      setSeasons([])
      setSeasonEpisodes([])
    }

    let cancelled = false
    fetchDetails(parsed.type, parsed.tmdbId)
      .then((details) => {
        if (cancelled) return
        cacheTitle(details)
        setOriginalLanguage(details.originalLanguage || null)
        if (parsed.type === 'show') setSeasons(details.seasons || [])
        const prev = usePlaybackStore.getState().title
        if (prev?.id === id) {
          setTitle({
            ...prev,
            title: details.title || prev.title,
            year: details.releaseYear ?? prev.year,
            overview: details.overview || prev.overview,
            poster: details.poster || prev.poster,
            backdrop: details.backdrop || prev.backdrop,
            isAnime: details.isAnime ?? prev.isAnime,
          })
        }
      })
      .catch(() => {
        if (!cancelled && parsed.type === 'show') setSeasons([])
      })
    return () => {
      cancelled = true
    }
  }, [parsed?.type, parsed?.tmdbId, id, setTitle])

  // Episode list for the active season (absolute numbering / next-ep accuracy)
  useEffect(() => {
    if (!parsed || parsed.type !== 'show') {
      setSeasonEpisodes([])
      return
    }
    const season = title?.id === id ? title.season || 1 : 1
    let cancelled = false
    fetchSeason(parsed.tmdbId, season)
      .then((details) => {
        if (!cancelled) setSeasonEpisodes(details.episodes || [])
      })
      .catch(() => {
        if (!cancelled) setSeasonEpisodes([])
      })
    return () => {
      cancelled = true
    }
  }, [parsed?.type, parsed?.tmdbId, title?.id, title?.season, id])

  // Invite link → nickname gate, then join
  useEffect(() => {
    const code = partyRoomParam(params)
    if (!code) return
    const state = usePartyStore.getState()
    if (state.enabled && state.roomCode === code.trim().toUpperCase()) return
    if (state.enabled && state.role === 'host' && state.roomCode === code.trim().toUpperCase()) return
    setPendingInvite(code)
    setNicknameNeeded(true)
    setPanelOpen(true)
    lookupPartyRoom(code)
      .then((room) => {
        setInvitePreview({ title: room.title, hostName: room.hostName })
        if (room.stream?.playable?.url) setHostStream(room.stream)
        if (room.contentId && room.contentId !== id) {
          // keep invite on redirect target
        }
      })
      .catch(() => {})
  }, [params.toString(), id, setPendingInvite, setNicknameNeeded, setPanelOpen, setHostStream])

  // Media "Watch party" → ?party=1 with no room: auto-host + open invite UI
  useEffect(() => {
    if (!id) return
    if (!params.get('party')) return
    if (partyRoomParam(params)) return

    const state = usePartyStore.getState()
    if (state.enabled && state.role === 'guest') return

    if (state.enabled && state.role === 'host' && state.roomCode) {
      setContentId(id)
      setPanelOpen(true)
      navigate(watchUrl(id, { party: true, room: state.roomCode, base: watchBase }), {
        replace: true,
      })
      return
    }

    const code = enableAsHost(id)
    setPanelOpen(true)
    navigate(watchUrl(id, { party: true, room: code, base: watchBase }), { replace: true })
  }, [
    id,
    params.get('party'),
    params.toString(),
    enableAsHost,
    setPanelOpen,
    setContentId,
    navigate,
    watchBase,
  ])

  // Resolve title details for slug paths / canonicalize watch URL
  useEffect(() => {
    if (!id || catalogItem || !parsed) return
    let cancelled = false
    resolveTitleFromPath(id).then((hit) => {
      if (cancelled || !hit) return
      const pathId = mediaKey(hit.title, hit.tmdbId, hit.type)
      if (title?.id !== pathId) {
        setTitle({
          id: pathId,
          type: hit.type,
          tmdbId: hit.tmdbId,
          title: hit.title,
          year: hit.releaseYear,
          overview: hit.overview,
          poster: hit.poster,
          backdrop: hit.backdrop || null,
          isAnime: hit.isAnime,
        })
      }
      if (pathId !== id) {
        const room = partyRoomParam(params)
        navigate(
          watchUrl(pathId, {
            party: params.has('party'),
            room: room || undefined,
            base: watchBase,
          }),
          { replace: true },
        )
      }
    })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, catalogItem, parsed?.tmdbId, watchBase])

  const applyHostProvider = useCallback(
    (stream: LabStream) => {
      const nextId = streamIdentity(stream)
      const current =
        usePlaybackStore.getState().streams[usePlaybackStore.getState().activeIndex] ||
        usePartyStore.getState().hostStream
      if (nextId && nextId === streamIdentity(current)) {
        setHostStream(stream)
        return
      }
      setHostStream(stream)
      resetStreams()
      addStream(stream)
      setActiveIndex(0)
      setRaceProgress({ racing: false, raceMessage: `Synced · ${stream.sourceName}` })
      setStatus(`Using host provider: ${stream.sourceName}`)
      setSelfReady(false)
    },
    [setHostStream, resetStreams, addStream, setActiveIndex, setRaceProgress, setSelfReady],
  )

  const raceEpisode = useCallback(
    async (season: number, episode: number) => {
      if (!id || !parsed || catalogItem) return
      raceAbortRef.current?.abort()
      const controller = new AbortController()
      raceAbortRef.current = controller
      setNextUp(null)
      resumeDoneRef.current = ''

      const prev = usePlaybackStore.getState().title
      setTitle({
        id,
        type: parsed.type,
        tmdbId: parsed.tmdbId,
        title: prev?.id === id ? prev.title : displayTitle,
        year: prev?.id === id ? prev.year : null,
        overview: prev?.id === id ? prev.overview : '',
        poster: prev?.id === id ? prev.poster : null,
        backdrop: prev?.id === id ? prev.backdrop : null,
        season: parsed.type === 'show' ? season : undefined,
        episode: parsed.type === 'show' ? episode : undefined,
        isAnime: prev?.id === id ? prev.isAnime : getCachedTitle(parsed.tmdbId, parsed.type)?.isAnime,
      })
      resetStreams()
      setSelfReady(false)
      setRaceProgress({ racing: true, raceTried: 0, raceTotal: 0, raceMessage: 'Racing…' })
      const epTag = parsed.type === 'show' ? ` S${season}E${episode}` : ''
      setStatus(`Racing providers${epTag}…`)

      try {
        await raceSources(
          {
            type: parsed.type,
            tmdbId: parsed.tmdbId,
            title: prev?.id === id ? prev.title : displayTitle,
            releaseYear: prev?.id === id ? prev.year ?? undefined : undefined,
            season: parsed.type === 'show' ? season : undefined,
            episode: parsed.type === 'show' ? episode : undefined,
          },
          {
            onStart: (data) => setRaceProgress({ raceTotal: data.total }),
            onProgress: (data) => {
              setRaceProgress({
                raceTried: data.tried,
                raceTotal: data.total,
                raceMessage: `${data.tried}/${data.total} · ${data.name}`,
              })
              setStatus(`Tried ${data.tried}/${data.total}`)
            },
            onStream: (stream) => addStream(stream),
            onDone: (data) => {
              setRaceProgress({ racing: false, raceMessage: `${data.playableCount} playable` })
              const state = usePlaybackStore.getState()
              const mode = readAudioMode()
              const lang =
                getCachedTitle(parsed.tmdbId, parsed.type)?.originalLanguage || originalLanguage || null
              if (state.streams.length && state.activeIndex < 0) {
                const preferred = pickStreamIndex(state.streams, mode, lang)
                if (preferred >= 0) {
                  setActiveIndex(preferred)
                } else if (resolveAudioMode(mode, lang) !== 'any') {
                  setStatus(
                    mode === 'dub'
                      ? `No dubbed sources${epTag} — switch to Sub or Any`
                      : `No Sub sources${epTag} — switch to Dub or Any`,
                  )
                  return
                }
              }
              setStatus(
                data.playableCount
                  ? `${data.playableCount} stream(s) found${epTag}`
                  : `No playable streams found${epTag}`,
              )
            },
            onError: (message) => setStatus(message),
          },
          controller.signal,
        )
      } catch (e) {
        const err = e as Error
        if (err.name !== 'AbortError') setStatus(err.message)
        setRaceProgress({ racing: false })
      }
    },
    [
      id,
      parsed,
      catalogItem,
      displayTitle,
      originalLanguage,
      setTitle,
      resetStreams,
      setSelfReady,
      setRaceProgress,
      addStream,
      setActiveIndex,
    ],
  )

  // Fill an initial source when nothing is selected yet. Never auto-swap after that —
  // source changes come from the user (menu / Sub-Dub toggle) or fatal failover.
  useEffect(() => {
    if (role === 'guest' || !streams.length || activeIndex >= 0) return
    const next = pickStreamIndex(streams, audioMode, originalLanguage)
    if (next >= 0) setActiveIndex(next)
  }, [originalLanguage, audioMode, streams, activeIndex, role, setActiveIndex])

  // Guests wait for host provider — do not race (avoids fighting host sync)
  useEffect(() => {
    if (!id || catalogItem || !parsed) return
    if (role === 'guest') {
      if (partyHostStream?.playable?.url) {
        applyHostProvider(partyHostStream)
      } else {
        setRaceProgress({ racing: false, raceMessage: 'Waiting for host…' })
        setStatus('Waiting for host to share their stream…')
      }
      return
    }
    if (title?.id === id && streams.length > 0) return

    const season = title?.id === id ? title.season || 1 : 1
    const episode = title?.id === id ? title.episode || 1 : 1
    void raceEpisode(season, episode)

    return () => raceAbortRef.current?.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, role, partyHostStream?.playable?.url])

  // Countdown → next episode
  useEffect(() => {
    if (!nextUp) return
    if (nextUp.seconds <= 0) {
      void raceEpisode(nextUp.season, nextUp.episode)
      return
    }
    const t = window.setTimeout(() => {
      setNextUp((prev) => (prev ? { ...prev, seconds: prev.seconds - 1 } : null))
    }, 1000)
    return () => window.clearTimeout(t)
  }, [nextUp, raceEpisode])

  const cancelNextUp = useCallback(() => setNextUp(null), [])

  const active = streams[activeIndex]
  const providerStream = active || partyHostStream

  const syncHandle = useMemo(() => {
    if (!id) return null
    return {
      contentId: id,
      title: displayTitle,
      getState: () =>
        playerRef.current?.getState() ?? { isPlaying: false, time: 0, duration: 0 },
      applyHostState: (s: { isPlaying: boolean; time: number }) =>
        playerRef.current?.applyHostState(s),
      getProvider: () => {
        const stream = usePlaybackStore.getState().streams[usePlaybackStore.getState().activeIndex]
        return stream || usePartyStore.getState().hostStream
      },
    }
  }, [id, displayTitle])

  const onHostContent = useCallback(
    (hostContentId: string) => {
      if (!hostContentId || hostContentId === id) return
      const code = roomCode || partyRoomParam(params) || ''
      setStatus('Following host to their title…')
      navigate(
        watchUrl(hostContentId, { party: true, room: code || undefined, base: watchBase }),
        { replace: true },
      )
    },
    [id, roomCode, params, navigate, watchBase],
  )

  const { sendChat, sendTransport, passControl, isController } = usePartySync(syncHandle, {
    onHostContent,
    onHostProvider: applyHostProvider,
  })

  const goNextEpisode = useCallback(() => {
    if (role === 'guest' || parsed?.type !== 'show' || !parsed.tmdbId) return
    const cur = usePlaybackStore.getState().title
    const season = cur?.id === id ? cur.season || 1 : 1
    const episode = cur?.id === id ? cur.episode || 1 : 1
    void resolveNextEpisode(parsed.tmdbId, seasons, season, episode).then((next) => {
      if (!next) {
        setStatus('End of available episodes')
        return
      }
      void raceEpisode(next.season, next.episode)
    })
  }, [role, parsed?.type, parsed?.tmdbId, id, seasons, raceEpisode])

  const onPlaybackEnded = useCallback(() => {
    if (role !== 'guest') {
      const cur = usePlaybackStore.getState().title
      if (cur?.tmdbId) {
        const state = playerRef.current?.getState()
        void upsertWatchProgress({
          type: cur.type,
          tmdbId: cur.tmdbId,
          pathId: cur.id,
          title: cur.title,
          poster: cur.poster,
          backdrop: cur.backdrop,
          year: cur.year,
          season: cur.season,
          episode: cur.episode,
          currentTime: state?.duration || state?.time || 0,
          duration: state?.duration || 0,
          completed: true,
        }).catch(() => {})
      }
    }
    if (role === 'guest') return
    if (enabled && !isController) return
    if (!autoNext || parsed?.type !== 'show') return
    const cur = usePlaybackStore.getState().title
    const tmdbId = cur?.tmdbId || parsed?.tmdbId
    const season = cur?.season || 1
    const episode = cur?.episode || 1
    if (!tmdbId) return
    void resolveNextEpisode(tmdbId, seasons, season, episode).then((next) => {
      if (!next) {
        setStatus('End of available episodes')
        return
      }
      setNextUp({ ...next, seconds: AUTO_NEXT_SECONDS })
    })
  }, [role, enabled, isController, autoNext, parsed?.type, parsed?.tmdbId, seasons])

  const saveWatchProgressNow = useCallback(
    (opts?: { completed?: boolean; force?: boolean }) => {
      if (role === 'guest') return
      const cur = usePlaybackStore.getState().title
      if (!cur?.tmdbId || cur.id !== id) return
      const state = playerRef.current?.getState()
      const time = state?.time ?? 0
      const duration = state?.duration ?? 0
      if (!opts?.force && time < 15 && !opts?.completed) return
      const now = Date.now()
      if (!opts?.force && !opts?.completed && now - lastSavedAtRef.current < 4000) return
      lastSavedAtRef.current = now
      void upsertWatchProgress({
        type: cur.type,
        tmdbId: cur.tmdbId,
        pathId: cur.id,
        title: cur.title,
        poster: cur.poster,
        backdrop: cur.backdrop,
        year: cur.year,
        season: cur.season,
        episode: cur.episode,
        currentTime: time,
        duration,
        completed: opts?.completed,
      }).catch(() => {})
    },
    [role, id],
  )

  const onTransport = useCallback(
    (action: 'play' | 'pause' | 'seek', time: number) => {
      sendTransport(action, time)
      if (action === 'pause' || action === 'seek') {
        saveWatchProgressNow({ force: true })
      }
    },
    [sendTransport, saveWatchProgressNow],
  )

  // Periodic + unload saves for continue watching.
  useEffect(() => {
    if (role === 'guest' || !id) return
    const tick = window.setInterval(() => saveWatchProgressNow(), 12_000)
    const flush = () => saveWatchProgressNow({ force: true })
    const onHide = () => {
      if (document.visibilityState === 'hidden') flush()
    }
    window.addEventListener('pagehide', flush)
    document.addEventListener('visibilitychange', onHide)
    return () => {
      window.clearInterval(tick)
      window.removeEventListener('pagehide', flush)
      document.removeEventListener('visibilitychange', onHide)
      flush()
    }
  }, [role, id, saveWatchProgressNow])

  const playerSource = useMemo(() => {
    if (catalogItem) {
      return {
        id: catalogItem.id,
        streamUrl: catalogItem.streamUrl,
        streamKind: catalogItem.streamKind,
        captions: [],
      }
    }
    if (providerStream?.playable?.url) {
      return {
        id: `${providerStream.sourceId}-${providerStream.embedId || 'direct'}-${activeIndex}`,
        streamUrl: providerStream.playable.url,
        streamKind: streamKindOf(providerStream),
        captions: providerStream.playable.captions || [],
      }
    }
    return null
  }, [catalogItem, providerStream, activeIndex])

  const aniskipQuery =
    title?.isAnime && parsed?.tmdbId
      ? {
          title: displayTitle || title.title || 'Anime',
          tmdbId: parsed.tmdbId,
          episode: title.episode || (parsed.type === 'movie' ? 1 : 0),
          year: title.year,
        }
      : null
  const aniskipQueryActive =
    aniskipQuery && aniskipQuery.episode > 0 ? aniskipQuery : null

  const onFatalError = useCallback(() => {
    const now = Date.now()
    // Debounce cascade (429 storms were hopping Link → Pseudo every second).
    if (now - fatalAtRef.current < 5000) return
    fatalAtRef.current = now

    // If we were already playing, do not steal the user's source (1080 → 720).
    if (usePartyStore.getState().selfReady) {
      setStatus('Stream stalled — staying on current source (retrying)…')
      return
    }

    setSelfReady(false)
    if (role === 'guest') {
      setStatus('Host stream failed to load — ask host to switch provider.')
      return
    }
    const mode = readAudioMode()
    const next = nextFailoverStreamIndex(streams, activeIndex, mode, originalLanguage)
    if (next >= 0) {
      const from = streams[activeIndex]
      const to = streams[next]
      setStatus(
        `Stream failed (${from?.sourceName || 'source'}) — trying ${to?.sourceName || 'next'}…`,
      )
      setActiveIndex(next)
    } else {
      setStatus('Playback failed on all found sources.')
    }
  }, [activeIndex, streams, setActiveIndex, setSelfReady, role, originalLanguage])

  const onPlayerReady = useCallback(() => {
    setSelfReady(true)
    setStatus((s) => (s.startsWith('Using host') ? s : 'Ready to play'))

    if (role === 'guest') return
    const cur = usePlaybackStore.getState().title
    if (!cur?.tmdbId || cur.id !== id) return
    const resumeKey = `${cur.type}:${cur.tmdbId}:s${cur.season || 1}e${cur.episode || 1}`
    if (resumeDoneRef.current === resumeKey) return
    resumeDoneRef.current = resumeKey
    void getWatchProgress(cur.type, cur.tmdbId, cur.season, cur.episode)
      .then((saved) => {
        if (!saved || saved.completed) return
        if (saved.currentTime < 20) return
        if (saved.duration > 0 && saved.currentTime / saved.duration >= 0.92) return
        playerRef.current?.applyHostState({
          isPlaying: autoPlay,
          time: saved.currentTime,
        })
        setStatus(`Resumed at ${Math.floor(saved.currentTime / 60)}m`)
      })
      .catch(() => {})
  }, [setSelfReady, role, id, autoPlay])

  const confirmNicknameJoin = async (nickname: string) => {
    const code = pendingInvite || partyRoomParam(params)
    if (!code) return
    setDisplayName(nickname)
    const room = await lookupPartyRoom(code)
    const target = room.contentId || id
    if (!target) throw new Error('Host has not opened a title yet')
    if (room.stream?.playable?.url) {
      setHostStream(room.stream)
      applyHostProvider(room.stream)
    }
    enableAsGuest(code, target)
    setContentId(target)
    setNicknameNeeded(false)
    setPendingInvite(null)
    if (target !== id) {
      navigate(watchUrl(target, { party: true, room: code, base: watchBase }), { replace: true })
    }
  }

  if (!id || (!catalogItem && !parsed)) {
    return (
      <div
        className={
          cinema
            ? 'demo-watch demo-watch-empty'
            : 'flex min-h-screen items-center justify-center bg-black'
        }
      >
        <Link to="/" className={cinema ? 'demo-btn demo-btn-ghost' : 'text-accent'}>
          Title not found — archive
        </Link>
      </div>
    )
  }

  const readyCount = peers.filter((p) =>
    p.userId === partyUserId ? selfReady : p.ready,
  ).length
  const partyBtnLabel =
    enabled && roomCode
      ? `Party ${roomCode} · ${readyCount}/${Math.max(peers.length, 1)}`
      : 'Party'

  const showAudioToggle = shouldShowAudioModeToggle(originalLanguage)

  const applyAudioMode = (mode: AudioMode) => {
    setAudioMode(mode)
    saveAudioMode(mode)
    if (role === 'guest' || !streams.length) return
    const next = pickStreamIndex(streams, mode, originalLanguage)
    if (next >= 0 && next !== activeIndex) {
      setSelfReady(false)
      setActiveIndex(next)
    } else if (next < 0) {
      setSelfReady(false)
      setActiveIndex(-1)
      setStatus(
        mode === 'dub'
          ? 'No dubbed sources found yet — try Sub or Any'
          : 'No subtitled sources found yet — try Any',
      )
    }
  }

  const visibleStreams =
    role === 'guest' ? streams : filterStreamsByAudio(streams, audioMode, originalLanguage)
  // Keep the source menu honest: Sub mode only lists Sub sources (don't leak Dub).
  const streamsForMenu = visibleStreams

  const sourceOptions =
    streamsForMenu.length > 0 && role !== 'guest'
      ? streamsForMenu.map((stream) => {
          const absoluteIndex = streams.indexOf(stream)
          return {
            id: `${stream.sourceId}-${stream.embedId || absoluteIndex}`,
            label: formatStreamLabel(stream, originalLanguage),
            index: absoluteIndex >= 0 ? absoluteIndex : 0,
          }
        })
      : undefined

  const currentSeason = title?.id === id ? title.season || 1 : 1
  const currentEpisode = title?.id === id ? title.episode || 1 : 1
  const nextEpisode =
    parsed?.type === 'show'
      ? nextEpisodeInSeries(seasons, currentSeason, currentEpisode, seasonEpisodes)
      : null

  const autoOpts =
    role !== 'guest' ? (
      <div className="demo-watch-auto-opts">
        <label className="demo-watch-autonext">
          <input
            type="checkbox"
            checked={autoPlay}
            onChange={(e) => {
              const on = e.target.checked
              setAutoPlay(on)
              saveAutoPlay(on)
            }}
          />
          Autoplay
        </label>
        {parsed?.type === 'show' ? (
          <>
            <span className="demo-watch-auto-sep" aria-hidden>
              |
            </span>
            <label className="demo-watch-autonext">
              <input
                type="checkbox"
                checked={autoNext}
                onChange={(e) => {
                  const on = e.target.checked
                  setAutoNext(on)
                  saveAutoNext(on)
                  if (!on) setNextUp(null)
                }}
              />
              Auto next
            </label>
          </>
        ) : null}
      </div>
    ) : null

  const episodesSlot =
    parsed?.type === 'show' && seasons.length && role !== 'guest' && parsed.tmdbId ? (
      <EpisodeCarousel
        tmdbId={parsed.tmdbId}
        seasons={seasons}
        season={currentSeason}
        episode={currentEpisode}
        onSelect={(s, e) => void raceEpisode(s, e)}
        variant="menu"
      />
    ) : null

  const sourceSelect =
    !cinema && streamsForMenu.length > 1 && role !== 'guest' ? (
      <select
        value={String(Math.max(activeIndex, 0))}
        onChange={(e) => {
          setSelfReady(false)
          setActiveIndex(Number(e.target.value))
        }}
        className={
          cinema
            ? 'demo-watch-select'
            : 'ml-2 max-w-[220px] truncate rounded-lg border border-white/10 bg-black/40 px-2 py-1 text-xs text-white'
        }
      >
        {streamsForMenu.map((stream) => {
          const index = streams.indexOf(stream)
          return (
            <option key={`${stream.sourceId}-${index}`} value={index >= 0 ? index : 0}>
              {formatStreamLabel(stream, originalLanguage)}
            </option>
          )
        })}
      </select>
    ) : !cinema && providerStream ? (
      <span className={cinema ? 'demo-watch-provider' : 'ml-2 truncate text-xs text-text-dim'}>
        {formatStreamLabel(providerStream, originalLanguage)}
      </span>
    ) : null

  if (cinema) {
    return (
      <div className="demo-watch is-immersive">
        <div className="demo-watch-stage is-bleed">
          <div className="demo-watch-player">
            {playerSource ? (
              <VideoPlayer
                ref={playerRef}
                source={playerSource}
                autoPlay={autoPlay}
                showAnimeUpscaler={Boolean(title?.isAnime)}
                aniskipQuery={aniskipQueryActive}
                onFatalError={onFatalError}
                onReady={onPlayerReady}
                readyAck={!enabled || selfReady}
                onEnded={onPlaybackEnded}
                onTransport={onTransport}
                canControl={!enabled || isController}
                skin="cinema"
                className="absolute inset-0 h-full w-full"
                title={displayTitle}
                subtitle={
                  episodeLabel
                    ? episodeLabel
                    : enabled
                      ? `Party ${roomCode}`
                      : undefined
                }
                topLeading={
                  <Link to={`/?details=${encodeURIComponent(id)}`} className="cinema-back">
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path
                        fill="currentColor"
                        d="M15.4 7.4 14 6l-6 6 6 6 1.4-1.4L10.8 12z"
                      />
                    </svg>
                    <span>Back</span>
                  </Link>
                }
                topTrailing={
                  <>
                    {autoOpts}
                    {showAudioToggle && role !== 'guest' ? (
                      <AudioModeToggle value={audioMode} onChange={applyAudioMode} compact />
                    ) : null}
                    {enabled ? (
                      <span className={`demo-watch-badge${isController ? ' is-control' : ''}`}>
                        {isController ? 'Control' : 'Following'}
                      </span>
                    ) : null}
                  </>
                }
                sourceOptions={sourceOptions}
                activeSourceIndex={activeIndex}
                onSelectSource={
                  role !== 'guest'
                    ? (index) => {
                        setSelfReady(false)
                        setActiveIndex(index)
                      }
                    : undefined
                }
                episodesSlot={episodesSlot}
                onNextEpisode={
                  parsed?.type === 'show' && role !== 'guest' ? goNextEpisode : undefined
                }
                nextEpisodeEnabled={
                  Boolean(nextEpisode) ||
                  (parsed?.type === 'show' &&
                    seasons.some((s) => s.seasonNumber > currentSeason))
                }
                subtitleQuery={
                  parsed
                    ? {
                        type: parsed.type,
                        tmdbId: parsed.tmdbId,
                        season: parsed.type === 'show' ? currentSeason : undefined,
                        episode: parsed.type === 'show' ? currentEpisode : undefined,
                      }
                    : undefined
                }
                partySlot={
                  <button
                    type="button"
                    className={[
                      'cinema-text-btn',
                      panelOpen || enabled ? 'is-active' : '',
                    ].join(' ')}
                    onClick={() => setPanelOpen(!panelOpen)}
                  >
                    {partyBtnLabel}
                  </button>
                }
              />
            ) : (
              <div className="demo-watch-loading">
                <Link to={`/?details=${encodeURIComponent(id)}`} className="cinema-back is-loading">
                  ← Back
                </Link>
                <div className="demo-watch-spinner" />
                <p>{racing ? 'Finding a playable stream…' : status || 'Waiting for stream…'}</p>
                <p className="demo-watch-sub">{raceMessage}</p>
                {role === 'guest' ? (
                  <p className="demo-watch-sub">
                    Guests sync the host’s provider automatically when it’s ready.
                  </p>
                ) : null}
              </div>
            )}

            {nextUp ? (
              <div className="demo-watch-nextup">
                <p>
                  Next up S{nextUp.season}E{nextUp.episode} in {nextUp.seconds}s
                </p>
                <div className="demo-watch-nextup-actions">
                  <button
                    type="button"
                    className="demo-btn demo-btn-primary"
                    onClick={() => void raceEpisode(nextUp.season, nextUp.episode)}
                  >
                    Play now
                  </button>
                  <button type="button" className="demo-btn demo-btn-ghost" onClick={cancelNextUp}>
                    Cancel
                  </button>
                </div>
              </div>
            ) : null}

            {enabled && showOverlay ? (
              <div className="demo-watch-overlay">
                Party {roomCode} · {readyCount}/{peers.length || 1} ready
                {selfReady ? ' · you ✓' : ' · loading…'}
                {isController ? ' · control' : ' · following'}
              </div>
            ) : null}
          </div>

          {panelOpen ? (
            <>
              <button
                type="button"
                className="demo-party-drawer-scrim"
                aria-label="Close party"
                onClick={() => setPanelOpen(false)}
              />
              <aside className="demo-party-drawer" aria-label="Watch party">
                <div className="demo-party-drawer-head">
                  <h2>Watch party</h2>
                  <button type="button" onClick={() => setPanelOpen(false)}>
                    Close
                  </button>
                </div>
                <div className="demo-party-drawer-body">
                  <PartyPanel
                    contentId={id}
                    title={displayTitle}
                    onSendChat={sendChat}
                    onPassControl={passControl}
                    compact
                  />
                  {enabled ? (
                    <div className="demo-party-drawer-chat">
                      <PartyChat onSend={sendChat} className="h-full" />
                    </div>
                  ) : null}
                </div>
              </aside>
            </>
          ) : null}
        </div>

        {nicknameNeeded && (pendingInvite || partyRoomParam(params)) ? (
          <NicknameGate
            title={invitePreview.title || displayTitle}
            hostName={invitePreview.hostName}
            onCancel={() => {
              setNicknameNeeded(false)
              setPendingInvite(null)
            }}
            onConfirm={(nick) => {
              void confirmNicknameJoin(nick).catch((e: Error) => alert(e.message))
            }}
          />
        ) : null}
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col bg-black">
      <div className="flex items-center gap-3 border-b border-white/5 bg-bg-chrome/90 px-3 py-2">
        <Link to={`${mediaBase}/${id}`} className="text-sm text-text-muted hover:text-white">
          ← Back
        </Link>
        <span className="truncate text-sm font-medium text-white">{watchHeading}</span>
        {autoOpts}
        {showAudioToggle && role !== 'guest' ? (
          <AudioModeToggle value={audioMode} onChange={applyAudioMode} compact />
        ) : null}
        {sourceSelect}
        <div className="ml-auto flex items-center gap-2">
          {enabled ? (
            <span
              className={[
                'hidden rounded-lg px-2 py-1 text-[11px] font-semibold sm:inline',
                isController ? 'bg-accent-deep text-white' : 'bg-white/10 text-text-muted',
              ].join(' ')}
            >
              {isController ? 'You have control' : 'Following'}
            </span>
          ) : null}
          <PartyDock
            contentId={id}
            title={displayTitle}
            onSendChat={sendChat}
            onPassControl={passControl}
            variant="watch"
          />
        </div>
      </div>

      <div className="relative flex min-h-0 flex-1 flex-col md:flex-row">
        <div className="relative min-h-0 min-w-0 flex-1 bg-black">
          {playerSource ? (
            <VideoPlayer
              ref={playerRef}
              source={playerSource}
              autoPlay={autoPlay}
              showAnimeUpscaler={Boolean(title?.isAnime)}
                aniskipQuery={aniskipQueryActive}
              onFatalError={onFatalError}
              onReady={onPlayerReady}
              readyAck={!enabled || selfReady}
              onEnded={onPlaybackEnded}
              onTransport={onTransport}
              canControl={!enabled || isController}
              skin="native"
              className="absolute inset-0 h-full w-full"
            />
          ) : (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 px-6 text-center text-sm text-text-muted">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-white/20 border-t-accent" />
              <p>{racing ? 'Finding a playable stream…' : status || 'Waiting for stream…'}</p>
              <p className="text-xs text-text-dim">{raceMessage}</p>
            </div>
          )}

          {nextUp ? (
            <div className="demo-watch-nextup">
              <p>
                Next up S{nextUp.season}E{nextUp.episode} in {nextUp.seconds}s
              </p>
              <div className="demo-watch-nextup-actions">
                <button
                  type="button"
                  className="demo-btn demo-btn-primary"
                  onClick={() => void raceEpisode(nextUp.season, nextUp.episode)}
                >
                  Play now
                </button>
                <button type="button" className="demo-btn demo-btn-ghost" onClick={cancelNextUp}>
                  Cancel
                </button>
              </div>
            </div>
          ) : null}

          {enabled && showOverlay ? (
            <div className="pointer-events-none absolute left-3 top-3 rounded-lg bg-black/70 px-3 py-1.5 text-xs text-white backdrop-blur">
              Party {roomCode} · {readyCount}/{peers.length || 1} ready
              {selfReady ? ' · you ✓' : ' · loading…'}
              {isController ? ' · control' : ' · following'}
            </div>
          ) : null}
        </div>

        {enabled ? (
          <aside className="flex h-52 w-full shrink-0 flex-col border-t border-white/10 bg-bg-chrome md:h-auto md:w-72 md:border-l md:border-t-0">
            <PartyChat onSend={sendChat} className="h-full" />
          </aside>
        ) : null}
      </div>

      {nicknameNeeded && (pendingInvite || partyRoomParam(params)) ? (
        <NicknameGate
          title={invitePreview.title || displayTitle}
          hostName={invitePreview.hostName}
          onCancel={() => {
            setNicknameNeeded(false)
            setPendingInvite(null)
          }}
          onConfirm={(nick) => {
            void confirmNicknameJoin(nick).catch((e: Error) => alert(e.message))
          }}
        />
      ) : null}
    </div>
  )
}
