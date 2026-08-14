/**
 * Google Cast Web Sender (CAF) helpers for CINEMAYA.
 * Uses the Default Media Receiver — stream URLs must be reachable by the Cast device
 * (open the app via your LAN IP, not localhost).
 */

export type CastAvailability = 'unknown' | 'unavailable' | 'available'
export type CastSessionState = 'idle' | 'connecting' | 'connected'

type CastListener = () => void

const DEFAULT_RECEIVER_ID = 'CC1AD845'
const CAST_SDK =
  'https://www.gstatic.com/cv/js/sender/v1/cast_sender.js?loadCastFramework=1'

declare global {
  interface Window {
    __onGCastApiAvailable?: (available: boolean, err?: unknown) => void
    chrome?: {
      cast?: {
        AutoJoinPolicy?: { ORIGIN_SCOPED: string }
        media?: {
          DEFAULT_MEDIA_RECEIVER_APP_ID?: string
          MediaInfo: new (url: string, contentType: string) => {
            metadata?: unknown
            streamType?: string
            duration?: number | null
            customData?: unknown
          }
          GenericMediaMetadata: new () => {
            metadataType: number
            title?: string
            subtitle?: string
          }
          MetadataType?: { GENERIC: number }
          StreamType?: { BUFFERED: string }
          LoadRequest: new (media: unknown) => {
            currentTime?: number
            autoplay?: boolean
          }
        }
      }
    }
    cast?: {
      framework?: {
        CastContext: {
          getInstance: () => CastContextLike
        }
        CastState: { NO_DEVICES_AVAILABLE: string; NOT_CONNECTED: string; CONNECTING: string; CONNECTED: string }
        SessionState: {
          NO_SESSION: string
          SESSION_STARTING: string
          SESSION_STARTED: string
          SESSION_ENDING: string
          SESSION_ENDED: string
          SESSION_RESUMED: string
        }
        CastContextEventType: { CAST_STATE_CHANGED: string; SESSION_STATE_CHANGED: string }
      }
    }
  }
}

type CastContextLike = {
  setOptions: (opts: Record<string, unknown>) => void
  getCastState: () => string
  getCurrentSession: () => CastSessionLike | null
  requestSession: () => Promise<void>
  endCurrentSession: (stopCasting: boolean) => void
  addEventListener: (type: string, fn: (e: unknown) => void) => void
  removeEventListener: (type: string, fn: (e: unknown) => void) => void
}

type CastSessionLike = {
  loadMedia: (req: unknown) => Promise<void>
  getCastDevice: () => { friendlyName?: string } | null
}

let sdkPromise: Promise<boolean> | null = null
let initialized = false
const listeners = new Set<CastListener>()

function notify() {
  for (const fn of listeners) {
    try {
      fn()
    } catch {
      /* ignore */
    }
  }
}

function framework() {
  return typeof window !== 'undefined' ? window.cast?.framework : undefined
}

export function subscribeCast(listener: CastListener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function isCastLocalhost(): boolean {
  if (typeof window === 'undefined') return true
  const host = window.location.hostname
  return host === 'localhost' || host === '127.0.0.1' || host === '[::1]'
}

/** Absolute media URL Chromecast can fetch (same-origin /api/proxy works when opened via LAN IP). */
export function castableMediaUrl(streamUrl: string): string {
  if (typeof window === 'undefined') return streamUrl
  try {
    return new URL(streamUrl, window.location.href).href
  } catch {
    return streamUrl
  }
}

export function contentTypeForStream(streamKind: 'hls' | 'file', url: string): string {
  if (streamKind === 'hls') return 'application/x-mpegURL'
  const lower = url.toLowerCase()
  if (lower.includes('.webm')) return 'video/webm'
  if (lower.includes('.mkv')) return 'video/x-matroska'
  return 'video/mp4'
}

export function getCastAvailability(): CastAvailability {
  const fw = framework()
  if (!fw || !initialized) return sdkPromise ? 'unknown' : 'unavailable'
  const state = fw.CastContext.getInstance().getCastState()
  if (state === fw.CastState.NO_DEVICES_AVAILABLE) return 'unavailable'
  return 'available'
}

export function getCastSessionState(): CastSessionState {
  const fw = framework()
  if (!fw || !initialized) return 'idle'
  const state = fw.CastContext.getInstance().getCastState()
  if (state === fw.CastState.CONNECTED) return 'connected'
  if (state === fw.CastState.CONNECTING) return 'connecting'
  return 'idle'
}

export function getCastDeviceName(): string | null {
  const fw = framework()
  if (!fw || !initialized) return null
  const session = fw.CastContext.getInstance().getCurrentSession()
  return session?.getCastDevice()?.friendlyName || null
}

function initCastContext() {
  const fw = framework()
  const chromeCast = window.chrome?.cast
  if (!fw || !chromeCast || initialized) return

  const receiverId =
    chromeCast.media?.DEFAULT_MEDIA_RECEIVER_APP_ID || DEFAULT_RECEIVER_ID

  const ctx = fw.CastContext.getInstance()
  ctx.setOptions({
    receiverApplicationId: receiverId,
    autoJoinPolicy: chromeCast.AutoJoinPolicy?.ORIGIN_SCOPED || 'origin_scoped',
    resumeSavedSession: true,
  })

  const onChange = () => notify()
  ctx.addEventListener(fw.CastContextEventType.CAST_STATE_CHANGED, onChange)
  ctx.addEventListener(fw.CastContextEventType.SESSION_STATE_CHANGED, onChange)
  initialized = true
  notify()
}

export function ensureCastSdk(): Promise<boolean> {
  if (typeof window === 'undefined') return Promise.resolve(false)
  if (framework() && initialized) return Promise.resolve(true)
  if (sdkPromise) return sdkPromise

  sdkPromise = new Promise((resolve) => {
    const prev = window.__onGCastApiAvailable
    window.__onGCastApiAvailable = (available) => {
      try {
        prev?.(available)
      } catch {
        /* ignore */
      }
      if (!available || !framework()) {
        resolve(false)
        notify()
        return
      }
      try {
        initCastContext()
        resolve(true)
      } catch {
        resolve(false)
      }
      notify()
    }

    if (framework()) {
      window.__onGCastApiAvailable(true)
      return
    }

    const existing = document.querySelector<HTMLScriptElement>('script[data-cinemaya-cast]')
    if (existing) return

    const script = document.createElement('script')
    script.src = CAST_SDK
    script.async = true
    script.dataset.cinemayaCast = '1'
    script.onerror = () => {
      resolve(false)
      notify()
    }
    document.head.appendChild(script)
  })

  return sdkPromise
}

export async function requestCastSession(): Promise<void> {
  const ok = await ensureCastSdk()
  if (!ok) throw new Error('Chromecast is not available in this browser')
  const fw = framework()
  if (!fw) throw new Error('Cast framework missing')
  await fw.CastContext.getInstance().requestSession()
}

export function endCastSession(stopCasting = true) {
  const fw = framework()
  if (!fw || !initialized) return
  fw.CastContext.getInstance().endCurrentSession(stopCasting)
}

export async function loadMediaOnCast(opts: {
  streamUrl: string
  streamKind: 'hls' | 'file'
  title?: string
  subtitle?: string
  currentTime?: number
  autoplay?: boolean
}): Promise<void> {
  const ok = await ensureCastSdk()
  if (!ok) throw new Error('Chromecast is not available in this browser')

  const fw = framework()
  const mediaApi = window.chrome?.cast?.media
  if (!fw || !mediaApi) throw new Error('Cast media API missing')

  let session = fw.CastContext.getInstance().getCurrentSession()
  if (!session) {
    await fw.CastContext.getInstance().requestSession()
    session = fw.CastContext.getInstance().getCurrentSession()
  }
  if (!session) throw new Error('No Cast session')

  const contentId = castableMediaUrl(opts.streamUrl)
  if (isCastLocalhost()) {
    throw new Error(
      'Open CINEMAYA via your LAN IP (not localhost) so Chromecast can reach the stream',
    )
  }

  const mediaInfo = new mediaApi.MediaInfo(
    contentId,
    contentTypeForStream(opts.streamKind, contentId),
  )
  const meta = new mediaApi.GenericMediaMetadata()
  meta.metadataType = mediaApi.MetadataType?.GENERIC ?? 0
  if (opts.title) meta.title = opts.title
  if (opts.subtitle) meta.subtitle = opts.subtitle
  mediaInfo.metadata = meta
  mediaInfo.streamType = mediaApi.StreamType?.BUFFERED || 'BUFFERED'

  const request = new mediaApi.LoadRequest(mediaInfo)
  request.currentTime = Math.max(0, opts.currentTime || 0)
  request.autoplay = opts.autoplay !== false

  await session.loadMedia(request)
}
