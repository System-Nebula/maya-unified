import type { LabStream } from '../api/lab'

/**
 * Watch-together transport over WebSocket (lab relay at /api/party).
 */

export type PartyWireMessage =
  | {
      type: 'join'
      roomCode: string
      userId: string
      displayName: string
      isHost: boolean
      contentId: string
      title?: string
      ready?: boolean
    }
  | {
      type: 'status'
      roomCode: string
      userId: string
      displayName: string
      isHost: boolean
      contentId: string
      title?: string
      ready?: boolean
      provider?: LabStream | null
      player?: {
        isPlaying: boolean
        time: number
        duration: number
      }
      controllerId?: string | null
    }
  | {
      type: 'chat'
      roomCode: string
      userId: string
      displayName: string
      message: string
      at: number
      system?: boolean
    }
  | {
      type: 'leave'
      roomCode: string
      userId: string
    }
  | {
      type: 'control'
      roomCode: string
      userId: string
      action: 'play' | 'pause' | 'seek'
      time?: number
    }
  | {
      type: 'pass-control'
      roomCode: string
      userId: string
      controllerId: string
    }

interface ChannelOptions {
  onOpen?: () => void
}

export function createPartyChannel(
  onMessage: (msg: PartyWireMessage) => void,
  options: ChannelOptions = {},
) {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const url = `${proto}//${window.location.host}/api/party`

  let ws: WebSocket | null = null
  let opened = false
  let intentionalClose = false
  let attempt = 0
  let reconnectTimer: number | null = null
  const queue: PartyWireMessage[] = []
  const onOpenRef = { current: options.onOpen }
  onOpenRef.current = options.onOpen

  const flush = () => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    while (queue.length) {
      ws.send(JSON.stringify(queue.shift()))
    }
  }

  const connect = () => {
    if (intentionalClose) return
    try {
      ws = new WebSocket(url)
    } catch {
      scheduleReconnect()
      return
    }

    ws.onopen = () => {
      opened = true
      attempt = 0
      flush()
      onOpenRef.current?.()
    }

    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(String(ev.data)) as PartyWireMessage
        if (data && typeof data === 'object' && 'type' in data) {
          onMessage(data)
        }
      } catch {
        /* ignore */
      }
    }

    ws.onerror = () => {
      /* onclose handles retry */
    }

    ws.onclose = () => {
      opened = false
      ws = null
      if (intentionalClose) return
      scheduleReconnect()
    }
  }

  const scheduleReconnect = () => {
    if (intentionalClose || reconnectTimer != null) return
    const delay = Math.min(8000, 400 * 2 ** attempt)
    attempt += 1
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null
      connect()
    }, delay)
  }

  connect()

  return {
    send(msg: PartyWireMessage) {
      if (opened && ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(msg))
      } else {
        queue.push(msg)
      }
    },
    close() {
      intentionalClose = true
      if (reconnectTimer != null) {
        window.clearTimeout(reconnectTimer)
        reconnectTimer = null
      }
      try {
        ws?.close()
      } catch {
        /* ignore */
      }
      ws = null
      opened = false
    },
  }
}
