import {
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  forwardRef,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react'
import Hls from 'hls.js'
import type { LabCaption } from '../api/lab'
import {
  fetchAniSkip,
  fetchExternalSubtitles,
  resolveExternalSubtitleUrl,
  type ExternalSubtitle,
} from '../api/lab'
import {
  captionToTrackSrc,
  dedupeCaptions,
  languageLabel,
  readSavedCcLang,
  saveCcLang,
} from '../lib/captions'
import {
  anime4kUnsupportedReason,
  isAnime4KSupported,
  readAnime4KEnabled,
  readAnime4KSettings,
  saveAnime4KEnabled,
  saveAnime4KSettings,
  startAnime4K,
  type Anime4KSession,
  type Anime4KSettings,
} from '../lib/anime4k'
import {
  formatHeightLabel,
  levelsToQualityOptions,
  pickAlwaysHdLevel,
  readAlwaysHd,
  readQualityPref,
  resolveInitialLevel,
  saveAlwaysHd,
  saveQualityPref,
  type QualityOption,
} from '../lib/streamQuality'
import {
  activeSkipAt,
  readAutoSkipIntro,
  readAutoSkipOutro,
  saveAutoSkipIntro,
  saveAutoSkipOutro,
  shouldAutoSkip,
  skipButtonLabel,
  type AniSkipSegment,
} from '../lib/aniskip'
import { TimelinePreviewCapturer } from '../lib/timelinePreview'
import {
  ensureCastSdk,
  endCastSession,
  getCastAvailability,
  getCastDeviceName,
  getCastSessionState,
  loadMediaOnCast,
  subscribeCast,
  type CastAvailability,
  type CastSessionState,
} from '../lib/chromecast'
import {
  DEFAULT_VIDEO_FILTERS,
  VideoProcessingPanel,
  type VideoFilterSettings,
} from './VideoProcessingPanel'

/** Chromecast UI — off until we have Cast-reachable (public/LAN) stream URLs. */
const CAST_UI_ENABLED = false

export interface VideoPlayerHandle {
  getState: () => { isPlaying: boolean; time: number; duration: number }
  applyHostState: (state: { isPlaying: boolean; time: number }) => void
  video: HTMLVideoElement | null
}

export interface PlayableSource {
  id: string
  streamUrl: string
  streamKind: 'hls' | 'file'
  captions?: LabCaption[]
}

type CcOption =
  | { kind: 'off'; id: 'off'; label: string }
  | { kind: 'external'; id: string; label: string; caption: LabCaption; badge?: string }
  | { kind: 'hls'; id: string; label: string; trackIndex: number }
  | {
      kind: 'opensubs'
      id: string
      label: string
      sub: ExternalSubtitle
      badge?: string
    }

type AudioOption = { id: string; label: string; trackIndex: number }

interface Props {
  source: PlayableSource
  className?: string
  /** Start playback when the stream is ready (default true). */
  autoPlay?: boolean
  onFatalError?: () => void
  onReady?: () => void
  /**
   * Parent's idea of ready (party selfReady). When false while media is
   * already buffered, re-fire onReady — starting a party resets ready without
   * remounting the player, which used to leave the host stuck "not ready".
   */
  readyAck?: boolean
  onEnded?: () => void
  onTransport?: (action: 'play' | 'pause' | 'seek', time: number) => void
  canControl?: boolean
  skin?: 'native' | 'cinema'
  /** Title shown in the Netflix-style top chrome */
  title?: string
  subtitle?: string
  /** Left side of top chrome (e.g. back link) */
  topLeading?: ReactNode
  /** Right side of top chrome (source, party, etc.) */
  topTrailing?: ReactNode
  /** Optional control next to fullscreen (party, next ep) */
  partySlot?: ReactNode
  /** Episodes menu panel (TV) */
  episodesSlot?: ReactNode
  /** Jump to next episode */
  onNextEpisode?: () => void
  nextEpisodeEnabled?: boolean
  /** Show Anime4K / 4K upscaler controls (anime titles only). */
  showAnimeUpscaler?: boolean
  /** AniSkip OP/ED for anime episodes (MAL via lab). */
  aniskipQuery?: {
    title: string
    tmdbId: string
    episode: number
    year?: number | null
  } | null
  /** Source picker entries shown in chrome (Aether-style) */
  sourceOptions?: { id: string; label: string; index: number }[]
  activeSourceIndex?: number
  onSelectSource?: (index: number) => void
  /** Used to pull OpenSubtitles / Wyzie tracks into the CC menu */
  subtitleQuery?: {
    type: 'movie' | 'show'
    tmdbId: string
    season?: number
    episode?: number
  }
}

function destroyHls(hls: Hls | null) {
  if (!hls) return
  try {
    hls.stopLoad()
  } catch {
    /* ignore */
  }
  try {
    hls.detachMedia()
  } catch {
    /* ignore */
  }
  try {
    hls.destroy()
  } catch {
    /* ignore */
  }
}

function formatTime(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00'
  const s = Math.floor(seconds)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = s % 60
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`
  return `${m}:${String(r).padStart(2, '0')}`
}

function IconPlay() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path fill="currentColor" d="M8 5v14l11-7z" />
    </svg>
  )
}

function IconPause() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path fill="currentColor" d="M6 5h4v14H6zm8 0h4v14h-4z" />
    </svg>
  )
}

function IconVolume() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M3 10v4h4l5 5V5L7 10H3zm13.5 2a4.5 4.5 0 0 0-2.3-3.9v7.8A4.5 4.5 0 0 0 16.5 12zM14 3.2v2.1a7 7 0 0 1 0 13.4v2.1a9 9 0 0 0 0-17.6z"
      />
    </svg>
  )
}

function IconMute() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M16.5 12a4.5 4.5 0 0 0-2.3-3.9l-1.4 1.4A2.5 2.5 0 0 1 14.5 12H16.5zM3 10v4h4l5 5V5L7 10H3zm13.1-5.1-1.4 1.4A7 7 0 0 1 19 12a7 7 0 0 1-1.2 3.9l1.4 1.4A9 9 0 0 0 21 12a9 9 0 0 0-4.9-7.1zM4.3 3 3 4.3 19.7 21 21 19.7 4.3 3z"
      />
    </svg>
  )
}

function IconSkipBack() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M12.5 3a9.5 9.5 0 1 0 9.5 9.5h-2A7.5 7.5 0 1 1 12.5 5v3.5L18 4.5 12.5 0V3z"
      />
      <text
        x="11.2"
        y="14.5"
        textAnchor="middle"
        fill="currentColor"
        fontSize="7.5"
        fontWeight="700"
        fontFamily="system-ui,sans-serif"
      >
        10
      </text>
    </svg>
  )
}

function IconSkipForward() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M11.5 3a9.5 9.5 0 1 1-9.5 9.5h2A7.5 7.5 0 1 0 11.5 5v3.5L6 4.5 11.5 0V3z"
      />
      <text
        x="12.8"
        y="14.5"
        textAnchor="middle"
        fill="currentColor"
        fontSize="7.5"
        fontWeight="700"
        fontFamily="system-ui,sans-serif"
      >
        10
      </text>
    </svg>
  )
}

function IconAnime4K() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zm1 2v10h14V7H5zm2.2 2.2h1.7l1.1 4.4 1.1-4.4h1.6L11.2 16H9.5L7.2 9.2zm7.1 0H19v1.3h-2.3V16h-1.4V9.2z"
      />
    </svg>
  )
}

function IconPip() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M19 7h-8v6h8V7zm2-4H3c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H3V5h18v14z"
      />
    </svg>
  )
}

function IconCast() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M21 3H3c-1.1 0-2 .9-2 2v3h2V5h18v14h-7v2h7c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zM1 18v3h3c0-1.66-1.34-3-3-3zm0-4v2c2.76 0 5 2.24 5 5h2c0-3.87-3.13-7-7-7zm0-4v2c4.97 0 9 4.03 9 9h2c0-6.08-4.93-11-11-11z"
      />
    </svg>
  )
}

function IconCastConnected() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M1 18v3h3c0-1.66-1.34-3-3-3zm0-4v2c2.76 0 5 2.24 5 5h2c0-3.87-3.13-7-7-7zm18-7H3v3h2V7h14v10h-5v2h5c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zM1 10v2c4.97 0 9 4.03 9 9h2c0-6.08-4.93-11-11-11z"
      />
    </svg>
  )
}

function IconEpisodes() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M4 6H2v14c0 1.1.9 2 2 2h14v-2H4V6zm16-4H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H8V4h12v12z"
      />
    </svg>
  )
}

function IconNextEp() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path fill="currentColor" d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z" />
    </svg>
  )
}

function IconFullscreen() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M7 14H5v5h5v-2H7v-3zm0-4h2V7h3V5H5v5h2zm10 7h-3v2h5v-5h-2v3zm0-12h-3v2h3v3h2V5h-2z"
      />
    </svg>
  )
}

function clearVideoTracks(video: HTMLVideoElement) {
  const tracks = video.querySelectorAll('track')
  tracks.forEach((t) => t.remove())
  for (let i = 0; i < video.textTracks.length; i++) {
    video.textTracks[i].mode = 'disabled'
  }
}

export const VideoPlayer = forwardRef<VideoPlayerHandle, Props>(function VideoPlayer(
  {
    source,
    className,
    autoPlay = true,
    onFatalError,
    onReady,
    readyAck = true,
    onEnded,
    onTransport,
    canControl = true,
    skin = 'native',
    title,
    subtitle,
    topLeading,
    topTrailing,
    partySlot,
    episodesSlot,
    onNextEpisode,
    nextEpisodeEnabled = false,
    showAnimeUpscaler = false,
    aniskipQuery = null,
    sourceOptions,
    activeSourceIndex = -1,
    onSelectSource,
    subtitleQuery,
  },
  ref,
) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const hlsRef = useRef<Hls | null>(null)
  const anime4kSessionRef = useRef<Anime4KSession | null>(null)
  const applyingRef = useRef(false)
  const readySentRef = useRef(false)
  const blobUrlsRef = useRef<string[]>([])
  const autoPlayRef = useRef(autoPlay)
  autoPlayRef.current = autoPlay
  const onReadyRef = useRef(onReady)
  const onFatalErrorRef = useRef(onFatalError)
  const onEndedRef = useRef(onEnded)
  const onTransportRef = useRef(onTransport)
  const canControlRef = useRef(canControl)
  onReadyRef.current = onReady
  onFatalErrorRef.current = onFatalError
  onEndedRef.current = onEnded
  onTransportRef.current = onTransport
  canControlRef.current = canControl

  // Parent cleared ready (party start / source change) but media is still
  // playable — re-ack so the host doesn't stay amber forever.
  useEffect(() => {
    if (readyAck) return
    const video = videoRef.current
    if (!video) return
    if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
      onReadyRef.current?.()
    }
  }, [readyAck, source.id, source.streamUrl])

  const [playing, setPlaying] = useState(false)
  const [muted, setMuted] = useState(false)
  const [volume, setVolume] = useState(1)
  const [volumeOpen, setVolumeOpen] = useState(false)
  const [castAvailability, setCastAvailability] = useState<CastAvailability>('unknown')
  const [castSession, setCastSession] = useState<CastSessionState>('idle')
  const [castDevice, setCastDevice] = useState<string | null>(null)
  const [castBusy, setCastBusy] = useState(false)
  const [castError, setCastError] = useState<string | null>(null)
  const [current, setCurrent] = useState(0)
  const [duration, setDuration] = useState(0)
  const [controlsVisible, setControlsVisible] = useState(true)
  const [ccOptions, setCcOptions] = useState<CcOption[]>([{ kind: 'off', id: 'off', label: 'Off' }])
  const [ccId, setCcId] = useState('off')
  const [audioOptions, setAudioOptions] = useState<AudioOption[]>([])
  const [audioId, setAudioId] = useState('')
  const [ccOpen, setCcOpen] = useState(false)
  const [audioOpen, setAudioOpen] = useState(false)
  const [sourceOpen, setSourceOpen] = useState(false)
  const [episodesOpen, setEpisodesOpen] = useState(false)
  const [qualityOpen, setQualityOpen] = useState(false)
  const [qualityOptions, setQualityOptions] = useState<QualityOption[]>([])
  const [qualityId, setQualityId] = useState('auto')
  const [alwaysHd, setAlwaysHd] = useState(() => readAlwaysHd())
  const [activeQualityLabel, setActiveQualityLabel] = useState('Auto')
  const [anime4kOn, setAnime4kOn] = useState(() => readAnime4KEnabled())
  const [anime4kReady, setAnime4kReady] = useState(() => isAnime4KSupported())
  const [anime4kBusy, setAnime4kBusy] = useState(false)
  const [anime4kError, setAnime4kError] = useState<string | null>(null)
  const [anime4kSettings, setAnime4kSettings] = useState<Anime4KSettings>(() =>
    readAnime4KSettings(),
  )
  const [anime4kPanelOpen, setAnime4kPanelOpen] = useState(false)
  const [videoFilters, setVideoFilters] = useState<VideoFilterSettings>(() => ({
    ...DEFAULT_VIDEO_FILTERS,
  }))
  const [skipSegments, setSkipSegments] = useState<AniSkipSegment[]>([])
  const [activeSkip, setActiveSkip] = useState<AniSkipSegment | null>(null)
  const [autoSkipIntro, setAutoSkipIntro] = useState(() => readAutoSkipIntro())
  const [autoSkipOutro, setAutoSkipOutro] = useState(() => readAutoSkipOutro())
  const [skipPrefsOpen, setSkipPrefsOpen] = useState(false)
  const skippedIdsRef = useRef<Set<string>>(new Set())
  const [ccQuery, setCcQuery] = useState('')
  const [externalSubs, setExternalSubs] = useState<ExternalSubtitle[]>([])
  const [externalHint, setExternalHint] = useState<string | null>(null)
  const [externalLoading, setExternalLoading] = useState(false)
  const externalLoadedFor = useRef<string>('')
  const [scrubHover, setScrubHover] = useState<{
    time: number
    ratio: number
  } | null>(null)
  const [scrubThumb, setScrubThumb] = useState<string | null>(null)
  const hideTimer = useRef<number | null>(null)
  const previewCapturer = useRef<TimelinePreviewCapturer | null>(null)
  const scrubDragging = useRef(false)
  const volumeLeaveTimer = useRef<number | null>(null)
  const anime4kSettingsRef = useRef(anime4kSettings)
  anime4kSettingsRef.current = anime4kSettings
  const pictureFilter = useMemo(
    () =>
      `brightness(${videoFilters.brightness}%) contrast(${videoFilters.contrast}%) saturate(${videoFilters.saturation}%)`,
    [videoFilters.brightness, videoFilters.contrast, videoFilters.saturation],
  )

  const bumpControls = () => {
    if (skin !== 'cinema') return
    setControlsVisible(true)
    if (hideTimer.current) window.clearTimeout(hideTimer.current)
    hideTimer.current = window.setTimeout(() => {
      const v = videoRef.current
      if (
        v &&
        !v.paused &&
        !ccOpen &&
        !audioOpen &&
        !sourceOpen &&
        !episodesOpen &&
        !qualityOpen &&
        !anime4kPanelOpen &&
        !volumeOpen
      ) {
        setControlsVisible(false)
      }
    }, 3200)
  }

  const revokeBlobs = () => {
    for (const url of blobUrlsRef.current) URL.revokeObjectURL(url)
    blobUrlsRef.current = []
  }

  const applyExternalCaption = async (caption: LabCaption | null) => {
    const video = videoRef.current
    if (!video) return
    clearVideoTracks(video)
    revokeBlobs()
    if (!caption) return

    try {
      const src = await captionToTrackSrc(caption)
      if (src.startsWith('blob:')) blobUrlsRef.current.push(src)
      const track = document.createElement('track')
      track.kind = 'subtitles'
      track.label = languageLabel(caption.language)
      track.srclang = caption.language || 'en'
      track.src = src
      track.default = true
      video.appendChild(track)
      // Enable after a tick so the browser registers the track
      window.setTimeout(() => {
        const list = video.textTracks
        for (let i = 0; i < list.length; i++) {
          list[i].mode = i === list.length - 1 ? 'showing' : 'disabled'
        }
      }, 50)
    } catch {
      /* caption failed — leave Off */
    }
  }

  const selectCc = async (option: CcOption) => {
    setCcId(option.id)
    setCcOpen(false)
    bumpControls()
    const hls = hlsRef.current

    if (option.kind === 'off') {
      saveCcLang(null)
      if (hls) hls.subtitleTrack = -1
      await applyExternalCaption(null)
      return
    }

    if (option.kind === 'hls') {
      saveCcLang(option.label)
      await applyExternalCaption(null)
      if (hls) hls.subtitleTrack = option.trackIndex
      return
    }

    if (option.kind === 'opensubs') {
      saveCcLang(option.sub.language || option.label)
      if (hls) hls.subtitleTrack = -1
      try {
        let url = option.sub.url
        if (!url && option.sub.fileId) {
          url = await resolveExternalSubtitleUrl(option.sub.fileId)
        }
        if (!url) throw new Error('No subtitle URL')
        await applyExternalCaption({
          url,
          language: option.sub.language,
          type: option.sub.type || 'srt',
        })
      } catch {
        /* leave Off */
        setCcId('off')
      }
      return
    }

    saveCcLang(option.caption.language || option.label)
    if (hls) hls.subtitleTrack = -1
    await applyExternalCaption(option.caption)
  }

  const selectAudio = (option: AudioOption) => {
    setAudioId(option.id)
    setAudioOpen(false)
    bumpControls()
    const hls = hlsRef.current
    if (hls) hls.audioTrack = option.trackIndex
  }

  const selectQuality = (option: QualityOption | { id: 'auto'; level: -1; label: 'Auto' }) => {
    setQualityId(option.id)
    setQualityOpen(false)
    bumpControls()
    const hls = hlsRef.current
    if (!hls) return
    if (option.id === 'auto') {
      saveQualityPref('auto')
      const hd = alwaysHd ? pickAlwaysHdLevel(qualityOptions) : null
      if (hd != null) hls.startLevel = hd
      hls.currentLevel = -1
      setActiveQualityLabel('Auto')
      return
    }
    const height = qualityOptions.find((q) => q.id === option.id)?.height
    if (height) saveQualityPref(String(height))
    hls.currentLevel = option.level
    setActiveQualityLabel(option.label)
  }

  const toggleAlwaysHd = () => {
    const next = !alwaysHd
    setAlwaysHd(next)
    saveAlwaysHd(next)
    bumpControls()
    const hls = hlsRef.current
    if (!hls || !qualityOptions.length) return
    if (qualityId !== 'auto') return
    const hd = next ? pickAlwaysHdLevel(qualityOptions) : null
    if (hd != null) hls.startLevel = hd
    hls.currentLevel = -1
    setActiveQualityLabel('Auto')
  }

  useEffect(() => {
    if (!ccOpen || !subtitleQuery?.tmdbId) return
    const key = `${subtitleQuery.type}:${subtitleQuery.tmdbId}:${subtitleQuery.season || ''}:${subtitleQuery.episode || ''}`
    if (externalLoadedFor.current === key) return
    let cancelled = false
    setExternalLoading(true)
    fetchExternalSubtitles(subtitleQuery)
      .then((data) => {
        if (cancelled) return
        externalLoadedFor.current = key
        setExternalSubs(data.results || [])
        setExternalHint(data.hint || null)
      })
      .catch(() => {
        if (!cancelled) {
          setExternalSubs([])
          setExternalHint('Could not load external subtitles')
        }
      })
      .finally(() => {
        if (!cancelled) setExternalLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [ccOpen, subtitleQuery?.type, subtitleQuery?.tmdbId, subtitleQuery?.season, subtitleQuery?.episode])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return

    let alive = true
    destroyHls(hlsRef.current)
    hlsRef.current = null
    clearVideoTracks(video)
    revokeBlobs()
    try {
      video.pause()
    } catch {
      /* ignore */
    }
    video.removeAttribute('src')
    video.load()
    readySentRef.current = false
    setPlaying(false)
    setCurrent(0)
    setDuration(0)
    setCcOpen(false)
    setAudioOpen(false)
    setQualityOpen(false)
    setAudioOptions([])
    setAudioId('')
    setQualityOptions([])
    setQualityId('auto')
    setActiveQualityLabel('Auto')

    const external = dedupeCaptions(source.captions || [])
    const baseCc: CcOption[] = [
      { kind: 'off', id: 'off', label: 'Off' },
      ...external.map((c, i) => ({
        kind: 'external' as const,
        id: `ext-${c.language || i}-${i}`,
        label: languageLabel(c.language),
        caption: c,
      })),
    ]
    setCcOptions(baseCc)
    setCcId('off')

    const markReady = () => {
      if (!alive) return
      const first = !readySentRef.current
      readySentRef.current = true
      onReadyRef.current?.()
      if (first && autoPlayRef.current) {
        void video.play().catch(() => {})
      }
    }

    let rateLimitTimer: number | null = null

    const onError = () => {
      // HLS owns network recovery; native <video> errors would double-fire failover.
      if (hlsRef.current) return
      if (alive) onFatalErrorRef.current?.()
    }

    const emitTransport = (action: 'play' | 'pause' | 'seek') => {
      if (!alive || applyingRef.current || !canControlRef.current) return
      onTransportRef.current?.(action, video.currentTime || 0)
    }

    const onPlay = () => {
      setPlaying(true)
      emitTransport('play')
      bumpControls()
    }
    const onPause = () => {
      setPlaying(false)
      emitTransport('pause')
      setControlsVisible(true)
    }
    const onSeeked = () => emitTransport('seek')
    const onTime = () => setCurrent(video.currentTime || 0)
    const onMeta = () => {
      setDuration(Number.isFinite(video.duration) ? video.duration : 0)
      setMuted(video.muted)
      setVolume(video.volume)
      if (source.streamKind === 'file' && video.videoHeight > 0) {
        const height = video.videoHeight
        setQualityOptions([
          {
            id: 'file',
            level: 0,
            label: formatHeightLabel(height),
            bitrateLabel: null,
            height,
          },
        ])
        setQualityId('file')
        setActiveQualityLabel(formatHeightLabel(height))
      }
    }
    const onVol = () => {
      setMuted(video.muted)
      setVolume(video.volume)
    }
    const onEndedEvent = () => {
      if (alive) onEndedRef.current?.()
    }

    video.addEventListener('error', onError)
    video.addEventListener('canplay', markReady)
    video.addEventListener('loadeddata', markReady)
    video.addEventListener('playing', markReady)
    video.addEventListener('play', onPlay)
    video.addEventListener('pause', onPause)
    video.addEventListener('seeked', onSeeked)
    video.addEventListener('timeupdate', onTime)
    video.addEventListener('loadedmetadata', onMeta)
    video.addEventListener('volumechange', onVol)
    video.addEventListener('ended', onEndedEvent)

    const preferLang = readSavedCcLang()

    const autoPickCc = (options: CcOption[]) => {
      if (!preferLang) return
      const match = options.find(
        (o) =>
          o.kind !== 'off' &&
          (o.label.toLowerCase() === preferLang.toLowerCase() ||
            (o.kind === 'external' &&
              (o.caption.language || '').toLowerCase() === preferLang.toLowerCase())),
      )
      if (match) void selectCc(match)
    }

    if (source.streamKind === 'hls') {
      if (Hls.isSupported()) {
        const hls = new Hls({
          enableWorker: true,
          lowLatencyMode: false,
          backBufferLength: 30,
          maxBufferLength: 30,
          enableWebVTT: true,
          enableIMSC1: false,
          enableCEA708Captions: false,
        })
        hls.loadSource(source.streamUrl)
        hls.attachMedia(video)
        hls.on(Hls.Events.MANIFEST_PARSED, () => {
          if (!alive) return
          markReady()

          const hlsSubs: CcOption[] = (hls.subtitleTracks || []).map((t, index) => ({
            kind: 'hls' as const,
            id: `hls-${index}`,
            label: languageLabel(t.lang || t.name || `Track ${index + 1}`),
            trackIndex: index,
          }))
          const merged = [
            { kind: 'off' as const, id: 'off', label: 'Off' },
            ...external.map((c, i) => ({
              kind: 'external' as const,
              id: `ext-${c.language || i}-${i}`,
              label: languageLabel(c.language),
              caption: c,
            })),
            ...hlsSubs,
          ]
          setCcOptions(merged)
          hls.subtitleTrack = -1

          const audios: AudioOption[] = (hls.audioTracks || []).map((t, index) => ({
            id: `audio-${index}`,
            label: languageLabel(t.lang || t.name || `Audio ${index + 1}`),
            trackIndex: index,
          }))
          setAudioOptions(audios.length > 1 ? audios : [])
          if (audios.length > 1) {
            const active = hls.audioTrack >= 0 ? hls.audioTrack : 0
            setAudioId(`audio-${active}`)
          }

          const applyQualities = (resetSelection: boolean) => {
            if (!alive) return
            const qualities = levelsToQualityOptions(hls.levels || [])
            setQualityOptions(qualities)
            if (!resetSelection) return
            if (qualities.length > 1) {
              const pref = readQualityPref()
              const always = readAlwaysHd()
              const initial = resolveInitialLevel(qualities, pref, always)
              if (initial < 0) {
                setQualityId('auto')
                setActiveQualityLabel('Auto')
                const hd = always ? pickAlwaysHdLevel(qualities) : null
                if (hd != null) hls.startLevel = hd
                hls.currentLevel = -1
              } else {
                const opt = qualities.find((q) => q.level === initial)
                setQualityId(opt?.id || 'auto')
                setActiveQualityLabel(opt?.label || 'Auto')
                hls.currentLevel = initial
              }
            } else if (qualities.length === 1) {
              setQualityId(qualities[0]!.id)
              setActiveQualityLabel(qualities[0]!.label)
            } else {
              setQualityId('auto')
              setActiveQualityLabel('Auto')
            }
          }

          applyQualities(true)
          hls.on(Hls.Events.LEVELS_UPDATED, () => applyQualities(false))

          autoPickCc(merged)
        })
        hls.on(Hls.Events.LEVEL_SWITCHED, (_e, data) => {
          if (!alive) return
          const level = hls.levels?.[data.level]
          const height = Number(level?.height) || 0
          const label = height ? formatHeightLabel(height) : 'Auto'
          setActiveQualityLabel(label)
          if (readAlwaysHd() && hls.autoLevelEnabled && height > 0 && height < 720) {
            const opts = levelsToQualityOptions(hls.levels || [])
            const hd = pickAlwaysHdLevel(opts)
            if (hd != null && hd !== data.level) hls.nextLevel = hd
          }
        })
        let networkRetries = 0
        let rateLimitRetries = 0
        // Successful media resets soft-error counters so a mid-watch 429
        // doesn't eventually force a source hop (Link 1080 → Pseudo 720).
        hls.on(Hls.Events.FRAG_LOADED, () => {
          networkRetries = 0
          rateLimitRetries = 0
        })
        hls.on(Hls.Events.ERROR, (_e, data) => {
          if (!alive) return
          const status = Number(data?.response?.code || 0)
          const hasStarted = readySentRef.current

          const retrySameSource = (delayMs: number) => {
            if (rateLimitTimer != null) window.clearTimeout(rateLimitTimer)
            rateLimitTimer = window.setTimeout(() => {
              rateLimitTimer = null
              if (!alive) return
              try {
                hls.startLoad()
              } catch {
                if (!hasStarted) onFatalErrorRef.current?.()
              }
            }, delayMs)
          }

          // Rate-limit: always stay on the current source once playback has
          // started — only fail over on initial load after a few tries.
          if (status === 429) {
            rateLimitRetries += 1
            const delay = Math.min(
              hasStarted ? 12_000 : 8000,
              1000 * 2 ** Math.min(rateLimitRetries - 1, 4),
            )
            if (hasStarted || rateLimitRetries <= 5) {
              retrySameSource(delay)
              return
            }
            onFatalErrorRef.current?.()
            return
          }
          // Hard auth / missing — fail over only before we've started watching.
          if (status === 401 || status === 403 || status === 404) {
            if (data?.fatal || data?.details?.includes?.('LOAD_ERROR')) {
              if (hasStarted) {
                retrySameSource(2000)
                return
              }
              onFatalErrorRef.current?.()
            }
            return
          }
          if (!data?.fatal) return
          try {
            if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
              if (hasStarted || networkRetries < 3) {
                networkRetries += 1
                retrySameSource(hasStarted ? 1500 : 500)
                return
              }
            }
            if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
              hls.recoverMediaError()
              return
            }
          } catch {
            /* fall through */
          }
          // Never auto-hop sources mid-watch; user can swap manually.
          if (!hasStarted) onFatalErrorRef.current?.()
        })
        hlsRef.current = hls
      } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
        video.src = source.streamUrl
        autoPickCc(baseCc)
      }
    } else {
      video.src = source.streamUrl
      autoPickCc(baseCc)
    }

    return () => {
      alive = false
      if (rateLimitTimer != null) window.clearTimeout(rateLimitTimer)
      if (hideTimer.current) window.clearTimeout(hideTimer.current)
      video.removeEventListener('error', onError)
      video.removeEventListener('canplay', markReady)
      video.removeEventListener('loadeddata', markReady)
      video.removeEventListener('playing', markReady)
      video.removeEventListener('play', onPlay)
      video.removeEventListener('pause', onPause)
      video.removeEventListener('seeked', onSeeked)
      video.removeEventListener('timeupdate', onTime)
      video.removeEventListener('loadedmetadata', onMeta)
      video.removeEventListener('volumechange', onVol)
      video.removeEventListener('ended', onEndedEvent)
      try {
        video.pause()
      } catch {
        /* ignore */
      }
      clearVideoTracks(video)
      revokeBlobs()
      destroyHls(hlsRef.current)
      hlsRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source.id, source.streamUrl, source.streamKind, skin])

  useImperativeHandle(ref, () => ({
    video: videoRef.current,
    getState: () => {
      const v = videoRef.current
      return {
        isPlaying: !!v && !v.paused && !v.ended,
        time: v?.currentTime ?? 0,
        duration: v?.duration && Number.isFinite(v.duration) ? v.duration : 0,
      }
    },
    applyHostState: ({ isPlaying, time }) => {
      const v = videoRef.current
      if (!v || applyingRef.current) return
      applyingRef.current = true
      try {
        const drift = Math.abs((v.currentTime || 0) - time)
        if (drift > 1.25) {
          v.currentTime = time
        }
        if (isPlaying && v.paused) {
          void v.play().catch(() => {})
        } else if (!isPlaying && !v.paused) {
          v.pause()
        }
      } finally {
        applyingRef.current = false
      }
    },
  }))

  const togglePlay = () => {
    const v = videoRef.current
    if (!v || !canControl) return
    bumpControls()
    if (v.paused) void v.play().catch(() => {})
    else v.pause()
  }

  const toggleMute = () => {
    const v = videoRef.current
    if (!v) return
    if (v.muted || v.volume === 0) {
      v.muted = false
      if (v.volume === 0) v.volume = volume > 0 ? volume : 0.5
      setMuted(false)
      setVolume(v.volume)
    } else {
      v.muted = true
      setMuted(true)
    }
    bumpControls()
  }

  const setVolumeLevel = (next: number) => {
    const v = videoRef.current
    if (!v) return
    const clamped = Math.min(1, Math.max(0, next))
    v.volume = clamped
    v.muted = clamped === 0
    setVolume(clamped)
    setMuted(v.muted)
    bumpControls()
  }

  const openVolume = () => {
    if (volumeLeaveTimer.current) {
      window.clearTimeout(volumeLeaveTimer.current)
      volumeLeaveTimer.current = null
    }
    setVolumeOpen(true)
    bumpControls()
  }

  const scheduleCloseVolume = () => {
    if (volumeLeaveTimer.current) window.clearTimeout(volumeLeaveTimer.current)
    volumeLeaveTimer.current = window.setTimeout(() => {
      setVolumeOpen(false)
      volumeLeaveTimer.current = null
    }, 220)
  }

  useEffect(() => {
    if (skin !== 'cinema') return
    const capturer = new TimelinePreviewCapturer()
    previewCapturer.current = capturer
    capturer.setMainVideo(videoRef.current)
    capturer.setSource({
      id: source.id,
      streamUrl: source.streamUrl,
      streamKind: source.streamKind,
    })
    return () => {
      capturer.destroy()
      previewCapturer.current = null
    }
  }, [skin, source.id, source.streamUrl, source.streamKind])

  // Keep the capturer pointed at the live <video> element.
  useEffect(() => {
    previewCapturer.current?.setMainVideo(videoRef.current)
  })

  useEffect(() => {
    setAnime4kReady(isAnime4KSupported())
  }, [])

  // Anime4K (bloc97) WebGPU upscale — anime titles only
  const anime4kPreset = anime4kSettings.preset
  const anime4kDarken = anime4kSettings.darkenLines
  const anime4kThin = anime4kSettings.thinLines
  const anime4kWorkgroup = anime4kSettings.workgroup
  useEffect(() => {
    if (!showAnimeUpscaler && anime4kOn) {
      setAnime4kOn(false)
      setAnime4kPanelOpen(false)
    }
  }, [showAnimeUpscaler, anime4kOn])

  useEffect(() => {
    if (skin !== 'cinema' || !showAnimeUpscaler || !anime4kOn || !anime4kReady) {
      anime4kSessionRef.current?.stop()
      anime4kSessionRef.current = null
      setAnime4kBusy(false)
      return
    }
    const video = videoRef.current
    const canvas = canvasRef.current
    if (!video || !canvas) return

    let cancelled = false
    setAnime4kBusy(true)
    setAnime4kError(null)

    const boot = async () => {
      try {
        if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
          await new Promise<void>((resolve) => {
            const done = () => {
              video.removeEventListener('loadeddata', done)
              resolve()
            }
            video.addEventListener('loadeddata', done)
          })
        }
        if (cancelled) return
        anime4kSessionRef.current?.stop()
        const session = await startAnime4K(video, canvas, anime4kSettingsRef.current)
        if (cancelled) {
          session.stop()
          return
        }
        anime4kSessionRef.current = session
      } catch (e) {
        if (cancelled) return
        setAnime4kOn(false)
        saveAnime4KEnabled(false)
        setAnime4kError(e instanceof Error ? e.message : 'Anime4K failed to start')
      } finally {
        if (!cancelled) setAnime4kBusy(false)
      }
    }
    void boot()

    return () => {
      cancelled = true
      anime4kSessionRef.current?.stop()
      anime4kSessionRef.current = null
    }
  }, [
    skin,
    anime4kOn,
    anime4kReady,
    anime4kPreset,
    anime4kDarken,
    anime4kThin,
    anime4kWorkgroup,
    source.id,
    source.streamUrl,
    showAnimeUpscaler,
  ])

  const openAnime4KPanel = () => {
    if (!showAnimeUpscaler) return
    setAnime4kPanelOpen(true)
    setCcOpen(false)
    setAudioOpen(false)
    setSourceOpen(false)
    setEpisodesOpen(false)
    setQualityOpen(false)
    bumpControls()
  }

  const applyAnime4KEnabled = (on: boolean) => {
    if (on && !anime4kReady) {
      setAnime4kError(anime4kUnsupportedReason() || 'WebGPU is required for Anime4K in this browser')
      bumpControls()
      return
    }
    setAnime4kOn(on)
    saveAnime4KEnabled(on)
    setAnime4kError(null)
    bumpControls()
  }

  const applyAnime4KSettings = (next: Anime4KSettings) => {
    setAnime4kSettings(next)
    saveAnime4KSettings(next)
    bumpControls()
  }

  const scrubRatioFromEvent = (e: ReactPointerEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    if (rect.width <= 0) return 0
    return Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width))
  }

  const updateScrubHover = (ratio: number) => {
    if (!duration) {
      setScrubHover(null)
      setScrubThumb(null)
      return
    }
    const time = ratio * duration
    setScrubHover({ time, ratio })
    previewCapturer.current?.request(time, (url) => {
      setScrubThumb(url)
    })
  }

  const seekToRatio = (ratio: number) => {
    const v = videoRef.current
    if (!v || !duration || !canControl) return
    v.currentTime = ratio * duration
    setCurrent(v.currentTime)
  }

  const onScrubPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    bumpControls()
    const ratio = scrubRatioFromEvent(e)
    updateScrubHover(ratio)
    if (!canControl) return
    scrubDragging.current = true
    try {
      e.currentTarget.setPointerCapture(e.pointerId)
    } catch {
      /* ignore */
    }
    seekToRatio(ratio)
  }

  const onScrubPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const ratio = scrubRatioFromEvent(e)
    updateScrubHover(ratio)
    if (scrubDragging.current && e.buttons === 1) {
      seekToRatio(ratio)
      bumpControls()
    }
  }

  const onScrubPointerUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (scrubDragging.current) {
      scrubDragging.current = false
      try {
        e.currentTarget.releasePointerCapture(e.pointerId)
      } catch {
        /* ignore */
      }
    }
  }

  const onScrubLeave = () => {
    if (scrubDragging.current) return
    setScrubHover(null)
    setScrubThumb(null)
  }

  const skipBy = (delta: number) => {
    const v = videoRef.current
    if (!v || !canControl) return
    const dur = Number.isFinite(v.duration) ? v.duration : duration
    const next = Math.min(Math.max(0, (v.currentTime || 0) + delta), dur || 0)
    v.currentTime = next
    setCurrent(next)
    bumpControls()
  }

  const seekAbsolute = (time: number, announce = true) => {
    const v = videoRef.current
    if (!v) return
    const dur = Number.isFinite(v.duration) ? v.duration : duration
    const next = Math.min(Math.max(0, time), dur > 0 ? dur : time)
    v.currentTime = next
    setCurrent(next)
    if (announce && canControl) onTransportRef.current?.('seek', next)
    bumpControls()
  }

  // AniSkip: load OP/ED markers for anime episodes.
  useEffect(() => {
    if (!aniskipQuery?.episode || !aniskipQuery.tmdbId) {
      setSkipSegments([])
      setActiveSkip(null)
      skippedIdsRef.current = new Set()
      return
    }
    let cancelled = false
    skippedIdsRef.current = new Set()
    setSkipSegments([])
    setActiveSkip(null)
    const epLen = duration > 30 ? duration : 0
    void fetchAniSkip({
      title: aniskipQuery.title,
      tmdbId: aniskipQuery.tmdbId,
      episode: aniskipQuery.episode,
      year: aniskipQuery.year,
      episodeLength: epLen || undefined,
    })
      .then((data) => {
        if (cancelled) return
        setSkipSegments(
          (data.results || []).map((r) => ({
            skipId: r.skipId,
            skipType: r.skipType,
            startTime: r.startTime,
            endTime: r.endTime,
            episodeLength: r.episodeLength,
          })),
        )
      })
      .catch(() => {
        if (!cancelled) setSkipSegments([])
      })
    return () => {
      cancelled = true
    }
  }, [
    aniskipQuery?.title,
    aniskipQuery?.tmdbId,
    aniskipQuery?.episode,
    aniskipQuery?.year,
    // Re-fetch once we know length so AniSkip can filter nearby durations.
    duration > 60 ? Math.round(duration) : 0,
  ])

  // Drive skip button + auto-skip from playback time.
  useEffect(() => {
    if (!skipSegments.length) {
      setActiveSkip(null)
      return
    }
    const hit = activeSkipAt(skipSegments, current)
    setActiveSkip(hit)
    if (!hit || !canControl) return
    if (skippedIdsRef.current.has(hit.skipId)) return
    if (!shouldAutoSkip(hit, autoSkipIntro, autoSkipOutro)) return
    // Only auto-skip once we've actually entered the segment.
    if (current < hit.startTime) return
    skippedIdsRef.current.add(hit.skipId)
    seekAbsolute(hit.endTime + 0.05)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, skipSegments, autoSkipIntro, autoSkipOutro, canControl])

  const skipActiveSegment = () => {
    if (!activeSkip || !canControl) return
    skippedIdsRef.current.add(activeSkip.skipId)
    seekAbsolute(activeSkip.endTime + 0.05)
    setActiveSkip(null)
  }

  const togglePip = async () => {
    const v = videoRef.current
    if (!v) return
    try {
      if (document.pictureInPictureElement) {
        await document.exitPictureInPicture()
      } else if (v.requestPictureInPicture) {
        await v.requestPictureInPicture()
      }
    } catch {
      /* ignore */
    }
    bumpControls()
  }

  useEffect(() => {
    if (!CAST_UI_ENABLED || skin !== 'cinema') return
    let cancelled = false
    void ensureCastSdk().then(() => {
      if (cancelled) return
      setCastAvailability(getCastAvailability())
      setCastSession(getCastSessionState())
      setCastDevice(getCastDeviceName())
    })
    const unsub = subscribeCast(() => {
      setCastAvailability(getCastAvailability())
      setCastSession(getCastSessionState())
      setCastDevice(getCastDeviceName())
    })
    return () => {
      cancelled = true
      unsub()
    }
  }, [skin])

  // Keep Cast media in sync when the local source changes while connected.
  useEffect(() => {
    if (!CAST_UI_ENABLED || skin !== 'cinema') return
    if (getCastSessionState() !== 'connected') return
    const v = videoRef.current
    void loadMediaOnCast({
      streamUrl: source.streamUrl,
      streamKind: source.streamKind,
      title,
      subtitle,
      currentTime: v?.currentTime || 0,
      autoplay: !v?.paused,
    }).catch(() => {
      /* ignore mid-switch failures */
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [skin, source.id, source.streamUrl, source.streamKind])

  const toggleCast = async () => {
    if (!CAST_UI_ENABLED) return
    bumpControls()
    setCastError(null)
    if (castSession === 'connected') {
      endCastSession(true)
      return
    }
    const v = videoRef.current
    setCastBusy(true)
    try {
      await loadMediaOnCast({
        streamUrl: source.streamUrl,
        streamKind: source.streamKind,
        title,
        subtitle,
        currentTime: v?.currentTime || 0,
        autoplay: true,
      })
      try {
        v?.pause()
      } catch {
        /* ignore */
      }
    } catch (e) {
      setCastError(e instanceof Error ? e.message : 'Cast failed')
    } finally {
      setCastBusy(false)
      setCastAvailability(getCastAvailability())
      setCastSession(getCastSessionState())
      setCastDevice(getCastDeviceName())
    }
  }

  const toggleFullscreen = () => {
    const root = rootRef.current
    if (!root) return
    if (document.fullscreenElement) {
      void document.exitFullscreen()
    } else {
      void root.requestFullscreen?.()
    }
    bumpControls()
  }

  const videoEl = (
    <video
      ref={videoRef}
      className={skin === 'cinema' ? 'cinema-video' : className ?? 'h-full w-full bg-black object-contain'}
      controls={skin === 'native'}
      playsInline
      crossOrigin="anonymous"
      style={skin === 'cinema' ? { filter: pictureFilter } : undefined}
      onClick={skin === 'cinema' ? togglePlay : undefined}
    />
  )

  const anime4kCanvas =
    skin === 'cinema' ? (
      <canvas
        ref={canvasRef}
        className={['cinema-anime4k', anime4kOn ? 'is-on' : ''].filter(Boolean).join(' ')}
        style={{ filter: pictureFilter }}
        aria-hidden={!anime4kOn}
      />
    ) : null

  if (skin !== 'cinema') {
    return videoEl
  }

  const progress = duration > 0 ? (current / duration) * 100 : 0
  const ccLabel =
    ccId === 'off' ? 'CC' : ccOptions.find((o) => o.id === ccId)?.label || 'CC'
  const openSubsOptions: CcOption[] = externalSubs.map((sub, i) => ({
    kind: 'opensubs' as const,
    id: `opensubs-${sub.id}-${i}`,
    label: languageLabel(sub.language),
    sub,
    badge: 'OPENSUBS',
  }))
  const allCcOptions: CcOption[] = [
    ...ccOptions,
    ...openSubsOptions.filter(
      (ext) =>
        !ccOptions.some(
          (o) =>
            o.kind !== 'off' &&
            o.label.toLowerCase() === ext.label.toLowerCase() &&
            o.kind === 'external',
        ),
    ),
  ]
  const q = ccQuery.trim().toLowerCase()
  const filteredCc = q
    ? allCcOptions.filter(
        (o) =>
          o.kind === 'off' ||
          o.label.toLowerCase().includes(q) ||
          (o.kind === 'opensubs' && (o.sub.language || '').includes(q)),
      )
    : allCcOptions
  const hasCcChoices = allCcOptions.length > 1
  const chromeOpen =
    controlsVisible ||
    ccOpen ||
    audioOpen ||
    sourceOpen ||
    episodesOpen ||
    qualityOpen ||
    anime4kPanelOpen ||
    volumeOpen ||
    !playing
  const activeSourceLabel =
    sourceOptions?.find((s) => s.index === activeSourceIndex)?.label ||
    sourceOptions?.[0]?.label ||
    'Source'
  const pipSupported =
    typeof document !== 'undefined' &&
    'pictureInPictureEnabled' in document &&
    Boolean(document.pictureInPictureEnabled)

  return (
    <div
      ref={rootRef}
      className={[
        'cinema-player',
        chromeOpen ? 'is-chrome' : 'is-idle',
        anime4kOn ? 'is-anime4k' : '',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      onMouseMove={bumpControls}
      onPointerDown={bumpControls}
    >
      {videoEl}
      {anime4kCanvas}

      {!playing ? (
        <button
          type="button"
          className={['cinema-big-play', chromeOpen ? 'is-visible' : ''].join(' ')}
          onClick={togglePlay}
          disabled={!canControl}
          aria-label="Play"
        >
          <IconPlay />
        </button>
      ) : null}

      <div className={['cinema-chrome', chromeOpen ? 'is-visible' : ''].join(' ')}>
        <div className="cinema-top">
          <div className="cinema-top-left">
            {topLeading}
            <div className="cinema-title-block">
              {title ? <p className="cinema-title">{title}</p> : null}
              {subtitle ? <p className="cinema-subtitle">{subtitle}</p> : null}
            </div>
          </div>
          <div className="cinema-top-right">{topTrailing}</div>
        </div>

        {activeSkip && canControl ? (
          <div className="cinema-aniskip-wrap">
            <button
              type="button"
              className="cinema-aniskip-btn"
              onClick={skipActiveSegment}
            >
              {skipButtonLabel(activeSkip.skipType)}
            </button>
          </div>
        ) : null}

        <div className="cinema-bottom">
          <div
            className={['cinema-scrub', scrubHover ? 'is-hovering' : ''].filter(Boolean).join(' ')}
            role="slider"
            aria-label="Seek"
            aria-valuemin={0}
            aria-valuemax={Math.floor(duration)}
            aria-valuenow={Math.floor(current)}
            tabIndex={canControl ? 0 : -1}
            onPointerDown={onScrubPointerDown}
            onPointerMove={onScrubPointerMove}
            onPointerUp={onScrubPointerUp}
            onPointerCancel={onScrubPointerUp}
            onPointerLeave={onScrubLeave}
          >
            {scrubHover ? (
              <div
                className="cinema-scrub-preview"
                style={{
                  left: `clamp(5.5rem, ${scrubHover.ratio * 100}%, calc(100% - 5.5rem))`,
                }}
              >
                {scrubThumb ? (
                  <img
                    className="cinema-scrub-preview-thumb"
                    src={scrubThumb}
                    alt=""
                    draggable={false}
                  />
                ) : (
                  <div className="cinema-scrub-preview-thumb is-empty" aria-hidden="true" />
                )}
                <span className="cinema-scrub-preview-time">{formatTime(scrubHover.time)}</span>
              </div>
            ) : null}
            <div className="cinema-scrub-track">
              {duration > 0
                ? skipSegments.map((seg) => {
                    const left = Math.max(0, Math.min(100, (seg.startTime / duration) * 100))
                    const right = Math.max(0, Math.min(100, (seg.endTime / duration) * 100))
                    const width = Math.max(0.45, right - left)
                    return (
                      <div
                        key={seg.skipId}
                        className={[
                          'cinema-scrub-skip',
                          activeSkip?.skipId === seg.skipId ? 'is-active' : '',
                        ]
                          .filter(Boolean)
                          .join(' ')}
                        style={{ left: `${left}%`, width: `${width}%` }}
                        title={`${skipButtonLabel(seg.skipType)} · ${formatTime(seg.startTime)}–${formatTime(seg.endTime)}`}
                        aria-hidden
                      />
                    )
                  })
                : null}
              {scrubHover ? (
                <div
                  className="cinema-scrub-hover"
                  style={{ width: `${scrubHover.ratio * 100}%` }}
                />
              ) : null}
              <div className="cinema-scrub-fill" style={{ width: `${progress}%` }}>
                <span className="cinema-scrub-knob" />
              </div>
            </div>
          </div>

          <div className="cinema-controls-row">
            <button
              type="button"
              className="cinema-icon-btn"
              onClick={togglePlay}
              disabled={!canControl}
              aria-label={playing ? 'Pause' : 'Play'}
            >
              {playing ? <IconPause /> : <IconPlay />}
            </button>
            <button
              type="button"
              className="cinema-icon-btn"
              onClick={() => skipBy(-10)}
              disabled={!canControl}
              aria-label="Back 10 seconds"
            >
              <IconSkipBack />
            </button>
            <button
              type="button"
              className="cinema-icon-btn"
              onClick={() => skipBy(10)}
              disabled={!canControl}
              aria-label="Forward 10 seconds"
            >
              <IconSkipForward />
            </button>
            <div
              className={['cinema-volume', volumeOpen ? 'is-open' : ''].filter(Boolean).join(' ')}
              onPointerEnter={openVolume}
              onPointerLeave={scheduleCloseVolume}
            >
              <button
                type="button"
                className="cinema-icon-btn"
                onClick={toggleMute}
                aria-label={muted || volume === 0 ? 'Unmute' : 'Mute'}
              >
                {muted || volume === 0 ? <IconMute /> : <IconVolume />}
              </button>
              <div className="cinema-volume-slider-wrap">
                <input
                  type="range"
                  className="cinema-volume-slider"
                  min={0}
                  max={1}
                  step={0.01}
                  value={muted ? 0 : volume}
                  aria-label="Volume"
                  onChange={(e) => setVolumeLevel(Number(e.target.value))}
                  onPointerDown={openVolume}
                />
              </div>
            </div>
            <span className="cinema-time">
              {formatTime(current)}
              <span className="cinema-time-sep">/</span>
              {formatTime(duration)}
            </span>
            {!canControl ? <span className="cinema-follow">Following</span> : null}

            <div className="cinema-controls-spacer" />

            {pipSupported ? (
              <button
                type="button"
                className="cinema-icon-btn"
                onClick={() => void togglePip()}
                aria-label="Picture in picture"
              >
                <IconPip />
              </button>
            ) : null}

            {CAST_UI_ENABLED && castAvailability !== 'unavailable' ? (
              <button
                type="button"
                className={[
                  'cinema-icon-btn',
                  castSession === 'connected' ? 'is-active' : '',
                  castBusy || castSession === 'connecting' ? 'is-busy' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
                onClick={() => void toggleCast()}
                disabled={castBusy || castSession === 'connecting'}
                aria-label={
                  castSession === 'connected'
                    ? `Stop casting${castDevice ? ` to ${castDevice}` : ''}`
                    : 'Cast to Chromecast'
                }
                title={
                  castError ||
                  (castSession === 'connected'
                    ? `Casting to ${castDevice || 'TV'}`
                    : 'Cast to Chromecast')
                }
              >
                {castSession === 'connected' ? <IconCastConnected /> : <IconCast />}
              </button>
            ) : null}

            {episodesSlot ? (
              <div className="cinema-menu-wrap">
                <button
                  type="button"
                  className={['cinema-text-btn', episodesOpen ? 'is-active' : ''].join(' ')}
                  onClick={() => {
                    setEpisodesOpen((v) => !v)
                    setSourceOpen(false)
                    setCcOpen(false)
                    setAudioOpen(false)
                    setQualityOpen(false)
                    setAnime4kPanelOpen(false)
                    bumpControls()
                  }}
                >
                  <IconEpisodes />
                  <span>Episodes</span>
                </button>
                {episodesOpen ? (
                  <div className="cinema-menu cinema-menu-wide" role="menu">
                    {episodesSlot}
                  </div>
                ) : null}
              </div>
            ) : null}

            {onNextEpisode ? (
              <button
                type="button"
                className="cinema-icon-btn"
                onClick={() => {
                  onNextEpisode()
                  bumpControls()
                }}
                disabled={!nextEpisodeEnabled || !canControl}
                aria-label="Next episode"
              >
                <IconNextEp />
              </button>
            ) : null}

            {sourceOptions && sourceOptions.length > 0 && onSelectSource ? (
              <div className="cinema-menu-wrap">
                <button
                  type="button"
                  className={['cinema-text-btn', sourceOpen ? 'is-active' : ''].join(' ')}
                  onClick={() => {
                    setSourceOpen((v) => !v)
                    setEpisodesOpen(false)
                    setCcOpen(false)
                    setAudioOpen(false)
                    setQualityOpen(false)
                    setAnime4kPanelOpen(false)
                    bumpControls()
                  }}
                  disabled={!canControl}
                >
                  {activeSourceLabel}
                </button>
                {sourceOpen ? (
                  <div className="cinema-menu" role="menu">
                    {sourceOptions.map((opt) => (
                      <button
                        key={`${opt.id}-${opt.index}`}
                        type="button"
                        role="menuitemradio"
                        aria-checked={opt.index === activeSourceIndex}
                        className={opt.index === activeSourceIndex ? 'is-active' : undefined}
                        onClick={() => {
                          onSelectSource(opt.index)
                          setSourceOpen(false)
                          bumpControls()
                        }}
                      >
                        {opt.label}
                        {opt.index === activeSourceIndex ? (
                          <span className="cinema-menu-check" aria-hidden="true">
                            ✓
                          </span>
                        ) : null}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}

            <div className="cinema-menu-wrap">
              <button
                type="button"
                className={['cinema-text-btn', ccId !== 'off' ? 'is-active' : ''].join(' ')}
                onClick={() => {
                  setCcOpen((v) => !v)
                  setQualityOpen(false)
                  setAudioOpen(false)
                  setSourceOpen(false)
                  setEpisodesOpen(false)
                  setAnime4kPanelOpen(false)
                  bumpControls()
                }}
              >
                {ccLabel}
              </button>
              {ccOpen ? (
                <div className="cinema-subs-panel" role="menu">
                  <div className="cinema-subs-head">
                    <p className="cinema-subs-title">Subtitles</p>
                  </div>
                  <input
                    className="cinema-subs-search"
                    value={ccQuery}
                    onChange={(e) => setCcQuery(e.target.value)}
                    placeholder="Search languages"
                    aria-label="Search subtitles"
                  />
                  <div className="cinema-subs-list">
                    {!hasCcChoices && !externalLoading ? (
                      <p className="cinema-menu-empty">
                        {externalHint || 'No subtitles for this title'}
                      </p>
                    ) : null}
                    {externalLoading ? (
                      <p className="cinema-menu-empty">Loading OpenSubtitles…</p>
                    ) : null}
                    {filteredCc.map((opt) => (
                      <button
                        key={opt.id}
                        type="button"
                        role="menuitemradio"
                        aria-checked={ccId === opt.id}
                        className={[
                          'cinema-subs-row',
                          ccId === opt.id ? 'is-active' : '',
                        ]
                          .filter(Boolean)
                          .join(' ')}
                        onClick={() => void selectCc(opt)}
                      >
                        <span className="cinema-subs-lang">{opt.label}</span>
                        <span className="cinema-subs-meta">
                          {opt.kind === 'opensubs' ||
                          (opt.kind === 'external' && opt.badge) ? (
                            <>
                              <span className="cinema-subs-tag">
                                {(opt.kind === 'opensubs'
                                  ? opt.sub.type
                                  : opt.caption.type) || 'SRT'}
                              </span>
                              <span className="cinema-subs-badge">OPENSUBS</span>
                            </>
                          ) : opt.kind === 'hls' ? (
                            <span className="cinema-subs-tag">HLS</span>
                          ) : opt.kind === 'external' ? (
                            <span className="cinema-subs-tag">
                              {(opt.caption.type || 'SRT').toUpperCase()}
                            </span>
                          ) : null}
                          {ccId === opt.id ? (
                            <span className="cinema-menu-check" aria-hidden="true">
                              ✓
                            </span>
                          ) : null}
                        </span>
                      </button>
                    ))}
                    {externalHint && hasCcChoices ? (
                      <p className="cinema-menu-empty">{externalHint}</p>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </div>

            {source.streamKind === 'hls' || qualityOptions.length > 0 ? (
              <div className="cinema-menu-wrap">
                <button
                  type="button"
                  className={['cinema-text-btn', qualityOpen ? 'is-active' : ''].join(' ')}
                  onClick={() => {
                    setQualityOpen((v) => !v)
                    setCcOpen(false)
                    setAudioOpen(false)
                    setSourceOpen(false)
                    setEpisodesOpen(false)
                    setAnime4kPanelOpen(false)
                    bumpControls()
                  }}
                >
                  {activeQualityLabel || 'Quality'}
                </button>
                {qualityOpen ? (
                  <div className="cinema-quality-panel" role="menu">
                    <div className="cinema-quality-head">
                      <button
                        type="button"
                        className="cinema-quality-back"
                        onClick={() => setQualityOpen(false)}
                        aria-label="Close quality"
                      >
                        ‹
                      </button>
                      <span className="cinema-quality-title">Quality</span>
                      <span className="cinema-quality-current">{activeQualityLabel}</span>
                    </div>

                    {source.streamKind === 'hls' && qualityOptions.length > 0 ? (
                      <div className="cinema-quality-always">
                        <span>Always HD</span>
                        <button
                          type="button"
                          className={['vp-switch', alwaysHd ? 'is-on' : ''].filter(Boolean).join(' ')}
                          role="switch"
                          aria-checked={alwaysHd}
                          onClick={toggleAlwaysHd}
                        >
                          <span className="vp-switch-knob" />
                        </button>
                      </div>
                    ) : null}

                    {source.streamKind === 'hls' ? (
                      <button
                        type="button"
                        role="menuitemradio"
                        aria-checked={qualityId === 'auto'}
                        className={[
                          'cinema-quality-row',
                          qualityId === 'auto' ? 'is-active' : '',
                        ]
                          .filter(Boolean)
                          .join(' ')}
                        onClick={() => selectQuality({ id: 'auto', level: -1, label: 'Auto' })}
                      >
                        <span className="cinema-quality-check" aria-hidden>
                          {qualityId === 'auto' ? '✓' : ''}
                        </span>
                        <span className="cinema-quality-label">Auto</span>
                      </button>
                    ) : null}

                    {qualityOptions.length === 0 ? (
                      <p className="cinema-menu-empty">Loading qualities…</p>
                    ) : (
                      qualityOptions.map((opt) => (
                        <button
                          key={opt.id}
                          type="button"
                          role="menuitemradio"
                          aria-checked={qualityId === opt.id}
                          className={[
                            'cinema-quality-row',
                            qualityId === opt.id ? 'is-active' : '',
                          ]
                            .filter(Boolean)
                            .join(' ')}
                          onClick={() => selectQuality(opt)}
                          disabled={source.streamKind === 'file'}
                        >
                          <span className="cinema-quality-check" aria-hidden>
                            {qualityId === opt.id ? '✓' : ''}
                          </span>
                          <span className="cinema-quality-label">{opt.label}</span>
                          {opt.bitrateLabel ? (
                            <span className="cinema-quality-bitrate">{opt.bitrateLabel}</span>
                          ) : null}
                        </button>
                      ))
                    )}
                  </div>
                ) : null}
              </div>
            ) : null}

            {audioOptions.length > 1 ? (
              <div className="cinema-menu-wrap">
                <button
                  type="button"
                  className="cinema-text-btn"
                  onClick={() => {
                    setAudioOpen((v) => !v)
                    setCcOpen(false)
                    setQualityOpen(false)
                    setSourceOpen(false)
                    setEpisodesOpen(false)
                    bumpControls()
                  }}
                >
                  Audio
                </button>
                {audioOpen ? (
                  <div className="cinema-menu" role="menu">
                    {audioOptions.map((opt) => (
                      <button
                        key={opt.id}
                        type="button"
                        role="menuitemradio"
                        aria-checked={audioId === opt.id}
                        className={audioId === opt.id ? 'is-active' : undefined}
                        onClick={() => selectAudio(opt)}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}

            {partySlot ? <div className="cinema-party-slot">{partySlot}</div> : null}

            {aniskipQuery ? (
              <div className="cinema-menu-wrap">
                <button
                  type="button"
                  className={[
                    'cinema-text-btn',
                    autoSkipIntro || autoSkipOutro || skipPrefsOpen ? 'is-active' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  onClick={() => {
                    setSkipPrefsOpen((v) => !v)
                    setCcOpen(false)
                    setQualityOpen(false)
                    setAudioOpen(false)
                    setSourceOpen(false)
                    setEpisodesOpen(false)
                    setAnime4kPanelOpen(false)
                    bumpControls()
                  }}
                  aria-label="Skip intro and outro"
                  title="Skip intro / outro"
                >
                  Skip
                </button>
                {skipPrefsOpen ? (
                  <div className="cinema-menu cinema-aniskip-prefs" role="menu">
                    <p className="cinema-aniskip-prefs-title">AniSkip</p>
                    <label className="cinema-aniskip-pref">
                      <input
                        type="checkbox"
                        checked={autoSkipIntro}
                        onChange={(e) => {
                          const on = e.target.checked
                          setAutoSkipIntro(on)
                          saveAutoSkipIntro(on)
                        }}
                      />
                      Auto-skip intro
                    </label>
                    <label className="cinema-aniskip-pref">
                      <input
                        type="checkbox"
                        checked={autoSkipOutro}
                        onChange={(e) => {
                          const on = e.target.checked
                          setAutoSkipOutro(on)
                          saveAutoSkipOutro(on)
                        }}
                      />
                      Auto-skip outro
                    </label>
                    {skipSegments.length ? (
                      <p className="cinema-aniskip-prefs-hint">
                        {skipSegments.length} marker{skipSegments.length === 1 ? '' : 's'} loaded
                      </p>
                    ) : (
                      <p className="cinema-aniskip-prefs-hint">No skip times for this episode</p>
                    )}
                  </div>
                ) : null}
              </div>
            ) : null}

            {showAnimeUpscaler ? (
              <button
                type="button"
                className={[
                  'cinema-text-btn',
                  anime4kOn || anime4kPanelOpen ? 'is-active' : '',
                  anime4kBusy ? 'is-busy' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
                onClick={openAnime4KPanel}
                aria-pressed={anime4kPanelOpen}
                aria-label="Anime4K upscaler"
                title={
                  anime4kError ||
                  (anime4kReady
                    ? 'Anime4K upscaler'
                    : anime4kUnsupportedReason() || 'Anime4K needs WebGPU')
                }
                disabled={anime4kBusy && !anime4kPanelOpen}
              >
                <IconAnime4K />
                <span>{anime4kBusy ? '4K…' : '4K'}</span>
              </button>
            ) : null}

            <button
              type="button"
              className="cinema-icon-btn"
              onClick={toggleFullscreen}
              aria-label="Fullscreen"
            >
              <IconFullscreen />
            </button>
          </div>
        </div>
      </div>

      {showAnimeUpscaler ? (
        <VideoProcessingPanel
          open={anime4kPanelOpen}
          onClose={() => setAnime4kPanelOpen(false)}
          enabled={anime4kOn}
          onEnabledChange={applyAnime4KEnabled}
          settings={anime4kSettings}
          onSettingsChange={applyAnime4KSettings}
          filters={videoFilters}
          onFiltersChange={setVideoFilters}
          busy={anime4kBusy}
          error={anime4kError}
        />
      ) : null}
    </div>
  )
})
