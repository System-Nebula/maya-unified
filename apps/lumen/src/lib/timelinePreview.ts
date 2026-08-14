import Hls from 'hls.js'

type PreviewSource = {
  id: string
  streamUrl: string
  streamKind: 'hls' | 'file'
}

/** Netflix-style scrub thumbnails via a secondary stream (never seeks the main player). */
export class TimelinePreviewCapturer {
  private mainVideo: HTMLVideoElement | null = null
  private video: HTMLVideoElement | null = null
  private hls: Hls | null = null
  private canvas: HTMLCanvasElement | null = null
  private cache = new Map<number, string>()
  private disabled = false
  private source: PreviewSource | null = null
  private seekTimer: number | null = null
  private idleTimer: number | null = null
  private pendingKey: number | null = null
  private onFrame: ((url: string | null) => void) | null = null
  private boundSeeked = () => this.paintSecondary()

  setMainVideo(video: HTMLVideoElement | null) {
    this.mainVideo = video
  }

  setSource(source: PreviewSource) {
    const key = `${source.id}|${source.streamUrl}|${source.streamKind}`
    const prev = this.source
      ? `${this.source.id}|${this.source.streamUrl}|${this.source.streamKind}`
      : ''
    if (key === prev) return
    this.destroySecondary()
    this.cache.clear()
    this.disabled = false
    this.source = source
    this.pendingKey = null
    this.onFrame?.(null)
  }

  request(time: number, onFrame: (url: string | null) => void) {
    this.onFrame = onFrame
    if (this.disabled || !this.source || !Number.isFinite(time)) {
      onFrame(null)
      return
    }

    const key = Math.max(0, Math.floor(time))
    const cached = this.cache.get(key)
    if (cached) {
      onFrame(cached)
      this.bumpIdle()
      return
    }

    this.pendingKey = key
    if (this.seekTimer != null) window.clearTimeout(this.seekTimer)
    // Debounce scrubbing so we don't open a second CDN session on every pixel move.
    this.seekTimer = window.setTimeout(() => {
      this.seekTimer = null
      void this.capture(key)
    }, 140)
    this.bumpIdle()
  }

  destroy() {
    if (this.seekTimer != null) window.clearTimeout(this.seekTimer)
    if (this.idleTimer != null) window.clearTimeout(this.idleTimer)
    this.seekTimer = null
    this.idleTimer = null
    this.onFrame = null
    this.mainVideo = null
    this.destroySecondary()
    this.cache.clear()
    this.source = null
  }

  private bumpIdle() {
    if (this.idleTimer != null) window.clearTimeout(this.idleTimer)
    // Drop the secondary session when the user stops scrubbing.
    this.idleTimer = window.setTimeout(() => {
      this.idleTimer = null
      this.destroySecondary()
    }, 3500)
  }

  private ensureCanvas() {
    if (!this.canvas) this.canvas = document.createElement('canvas')
    return this.canvas
  }

  private paintFrame(video: HTMLVideoElement, key: number) {
    if (!video.videoWidth) return null
    const canvas = this.ensureCanvas()
    const w = 320
    const h = Math.max(1, Math.round((video.videoHeight / Math.max(1, video.videoWidth)) * w) || 180)
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    ctx.drawImage(video, 0, 0, w, h)
    const url = canvas.toDataURL('image/jpeg', 0.72)
    this.cache.set(key, url)
    if (this.cache.size > 80) {
      const first = this.cache.keys().next().value
      if (first != null) this.cache.delete(first)
    }
    return url
  }

  private async capture(key: number) {
    if (this.pendingKey !== key || this.disabled) return

    // Never seek the main player for previews — that jumps playback.
    // Only snag a frame if the main video is already sitting on that second.
    const main = this.mainVideo
    if (main && main.readyState >= 2 && Math.abs(main.currentTime - key) < 0.6) {
      const url = this.paintFrame(main, key)
      if (url) {
        this.onFrame?.(url)
        return
      }
    }

    await this.captureFromSecondary(key)
  }

  private ensureSecondary() {
    if (this.video || this.disabled || !this.source) return
    const video = document.createElement('video')
    video.muted = true
    video.playsInline = true
    video.preload = 'auto'
    video.crossOrigin = 'anonymous'
    video.setAttribute('playsinline', '')
    video.style.cssText =
      'position:fixed;left:-9999px;width:1px;height:1px;opacity:0;pointer-events:none'
    document.body.appendChild(video)
    video.addEventListener('seeked', this.boundSeeked)

    if (this.source.streamKind === 'hls' && Hls.isSupported()) {
      const hls = new Hls({
        enableWorker: true,
        // Tiny buffer + lowest rung only — preview must not compete with playback.
        maxBufferLength: 2,
        maxMaxBufferLength: 4,
        backBufferLength: 0,
        startLevel: 0,
        autoStartLoad: true,
        capLevelToPlayerSize: true,
      })
      hls.loadSource(this.source.streamUrl)
      hls.attachMedia(video)
      hls.on(Hls.Events.ERROR, (_e, data) => {
        const status = Number(data?.response?.code || 0)
        if (status === 429 || status === 403 || (data?.fatal && data.type === Hls.ErrorTypes.NETWORK_ERROR)) {
          this.disableSecondaryOnly()
        }
      })
      // Lock to lowest quality after levels are known.
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        try {
          hls.currentLevel = 0
          hls.loadLevel = 0
        } catch {
          /* ignore */
        }
      })
      this.hls = hls
    } else {
      video.src = this.source.streamUrl
    }

    this.video = video
    this.ensureCanvas()
  }

  private async captureFromSecondary(key: number) {
    this.ensureSecondary()
    const video = this.video
    if (!video || this.disabled) {
      this.onFrame?.(null)
      return
    }

    try {
      if (video.readyState < 1) {
        await new Promise<void>((resolve, reject) => {
          const ok = () => {
            cleanup()
            resolve()
          }
          const fail = () => {
            cleanup()
            reject(new Error('preview metadata failed'))
          }
          const cleanup = () => {
            video.removeEventListener('loadedmetadata', ok)
            video.removeEventListener('error', fail)
          }
          video.addEventListener('loadedmetadata', ok, { once: true })
          video.addEventListener('error', fail, { once: true })
          window.setTimeout(fail, 8000)
        })
      }
    } catch {
      this.disableSecondaryOnly()
      return
    }

    if (this.pendingKey !== key) return
    try {
      const duration = Number.isFinite(video.duration) ? video.duration : key
      video.currentTime = Math.min(key + 0.001, Math.max(0, duration - 0.05))
    } catch {
      this.disableSecondaryOnly()
    }
  }

  private paintSecondary() {
    const video = this.video
    const key = this.pendingKey
    if (!video || key == null || this.disabled) return
    if (Math.floor(video.currentTime) !== key && Math.abs(video.currentTime - key) > 1.25) {
      return
    }
    try {
      const url = this.paintFrame(video, key)
      if (url) this.onFrame?.(url)
    } catch {
      this.disableSecondaryOnly()
    }
  }

  /** Keep main playback; only kill the preview helper after rate-limits. */
  private disableSecondaryOnly() {
    this.destroySecondary()
    this.onFrame?.(null)
  }

  private destroySecondary() {
    if (this.video) {
      this.video.removeEventListener('seeked', this.boundSeeked)
      try {
        this.video.pause()
      } catch {
        /* ignore */
      }
      this.video.removeAttribute('src')
      try {
        this.video.load()
      } catch {
        /* ignore */
      }
      this.video.remove()
    }
    this.video = null
    if (this.hls) {
      try {
        this.hls.destroy()
      } catch {
        /* ignore */
      }
      this.hls = null
    }
  }
}
