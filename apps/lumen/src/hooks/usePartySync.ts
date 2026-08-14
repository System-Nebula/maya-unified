import { useEffect, useRef } from 'react'
import { streamIdentity, type LabStream } from '../api/lab'
import { createPartyChannel } from '../party/channel'
import { usePartyStore } from '../stores/party'

export interface PlayerSyncHandle {
  getState: () => { isPlaying: boolean; time: number; duration: number }
  applyHostState: (state: { isPlaying: boolean; time: number }) => void
  contentId: string
  title?: string
  getProvider?: () => LabStream | null
}

export interface PartySyncOptions {
  onHostContent?: (contentId: string, title?: string) => void
  onHostProvider?: (stream: LabStream) => void
}

function hostUserId(peers: { userId: string; isHost: boolean }[], fallback: string) {
  return peers.find((p) => p.isHost)?.userId || fallback
}

function holdingControl(store: {
  controllerId: string | null
  userId: string
  role: string | null
}) {
  return (
    store.controllerId === store.userId ||
    (!store.controllerId && store.role === 'host')
  )
}

export function usePartySync(handle: PlayerSyncHandle | null, options: PartySyncOptions = {}) {
  const enabled = usePartyStore((s) => s.enabled)
  const roomCode = usePartyStore((s) => s.roomCode)
  const role = usePartyStore((s) => s.role)
  const userId = usePartyStore((s) => s.userId)
  const displayName = usePartyStore((s) => s.displayName)
  const selfReady = usePartyStore((s) => s.selfReady)
  const controllerId = usePartyStore((s) => s.controllerId)
  const channelRef = useRef<ReturnType<typeof createPartyChannel> | null>(null)
  const handleRef = useRef(handle)
  handleRef.current = handle
  const onHostContentRef = useRef(options.onHostContent)
  onHostContentRef.current = options.onHostContent
  const onHostProviderRef = useRef(options.onHostProvider)
  onHostProviderRef.current = options.onHostProvider
  const selfReadyRef = useRef(selfReady)
  selfReadyRef.current = selfReady
  const roleRef = useRef(role)
  roleRef.current = role
  const controllerIdRef = useRef(controllerId)
  controllerIdRef.current = controllerId
  const lastHostProviderIdRef = useRef('')
  const lastAppliedPlayerRef = useRef({ isPlaying: false, time: -1 })
  const catchUpUntilRef = useRef(0)
  const pendingPlayerRef = useRef<{ isPlaying: boolean; time: number } | null>(null)

  useEffect(() => {
    if (!enabled || !roomCode || !handle) return

    lastHostProviderIdRef.current = ''
    lastAppliedPlayerRef.current = { isPlaying: false, time: -1 }
    pendingPlayerRef.current = null
    catchUpUntilRef.current = Date.now() + 12_000

    const isControllerNow = () => {
      const store = usePartyStore.getState()
      return holdingControl({ ...store, role: roleRef.current })
    }

    const applyPlayer = (player: { isPlaying: boolean; time: number }, force = false) => {
      const h = handleRef.current
      pendingPlayerRef.current = player
      if (!h) return
      const prev = lastAppliedPlayerRef.current
      const drift = Math.abs((player.time ?? 0) - prev.time)
      const inCatchUp = Date.now() < catchUpUntilRef.current
      if (!force && !inCatchUp && player.isPlaying === prev.isPlaying && drift <= 1.25) return
      lastAppliedPlayerRef.current = {
        isPlaying: player.isPlaying,
        time: player.time ?? 0,
      }
      h.applyHostState({
        isPlaying: player.isPlaying,
        time: player.time,
      })
    }

    const sendControlSnapshot = () => {
      const h = handleRef.current
      if (!h || !channelRef.current || !isControllerNow()) return
      const player = h.getState()
      channelRef.current.send({
        type: 'control',
        roomCode,
        userId,
        action: player.isPlaying ? 'play' : 'pause',
        time: player.time,
      })
    }

    const sendPresence = (type: 'join' | 'status') => {
      const h = handleRef.current
      if (!h || !channelRef.current) return
      const store = usePartyStore.getState()
      const player = h.getState()
      const isController = isControllerNow()

      if (type === 'join') {
        channelRef.current.send({
          type: 'join',
          roomCode,
          userId,
          displayName: store.displayName || 'Viewer',
          isHost: roleRef.current === 'host',
          contentId: h.contentId,
          title: h.title,
          ready: selfReadyRef.current,
        })
        return
      }

      channelRef.current.send({
        type: 'status',
        roomCode,
        userId,
        displayName: store.displayName || 'Viewer',
        isHost: roleRef.current === 'host',
        contentId: h.contentId,
        title: h.title,
        ready: selfReadyRef.current,
        provider: roleRef.current === 'host' ? h.getProvider?.() || null : null,
        player: isController ? player : undefined,
        // Only the room host advertises controller — guest heartbeats were
        // overwriting pass-control and flipping control back and forth.
        controllerId:
          roleRef.current === 'host' ? store.controllerId || userId : undefined,
      })
    }

    const channel = createPartyChannel(
      (msg) => {
        if (msg.roomCode !== roomCode) return
        if (msg.type !== 'leave' && 'userId' in msg && msg.userId === userId) return

        const store = usePartyStore.getState()
        const h = handleRef.current

        switch (msg.type) {
          case 'join': {
            store.upsertPeer({
              userId: msg.userId,
              displayName: msg.displayName,
              isHost: msg.isHost,
              ready: Boolean(msg.ready),
              lastUpdate: Date.now(),
            })
            store.addChat({
              userId: msg.userId,
              displayName: msg.displayName || 'Viewer',
              message: 'joined',
              system: true,
            })
            // Everyone answers; controller also snaps play/pause + time immediately
            sendPresence('status')
            if (isControllerNow()) {
              sendControlSnapshot()
            }
            break
          }
          case 'status': {
            store.upsertPeer({
              userId: msg.userId,
              displayName: msg.displayName,
              isHost: msg.isHost,
              ready: Boolean(msg.ready),
              lastUpdate: Date.now(),
            })

            // Authoritative controller comes from host status or pass-control only.
            if (msg.isHost && msg.controllerId) {
              store.setControllerId(msg.controllerId)
              controllerIdRef.current = msg.controllerId
            }

            if (msg.isHost && h) {
              if (msg.contentId && msg.contentId !== h.contentId) {
                store.setContentId(msg.contentId)
                onHostContentRef.current?.(msg.contentId, msg.title)
                return
              }
              if (roleRef.current === 'guest' && msg.provider?.playable?.url) {
                const id = streamIdentity(msg.provider)
                if (id && id !== lastHostProviderIdRef.current) {
                  lastHostProviderIdRef.current = id
                  store.setHostStream(msg.provider)
                  onHostProviderRef.current?.(msg.provider)
                }
              }
            }

            const activeController = usePartyStore.getState().controllerId
            if (
              msg.player &&
              activeController &&
              msg.userId === activeController &&
              msg.userId !== userId
            ) {
              applyPlayer(msg.player, true)
            }
            break
          }
          case 'chat': {
            store.addChat({
              userId: msg.userId,
              displayName: msg.displayName,
              message: msg.message,
              at: msg.at,
              self: false,
              system: Boolean(msg.system),
            })
            break
          }
          case 'leave': {
            const nextPeers = store.peers.filter((p) => p.userId !== msg.userId)
            const left = store.peers.find((p) => p.userId === msg.userId)
            store.setPeers(nextPeers)
            if (left) {
              store.addChat({
                userId: left.userId,
                displayName: left.displayName,
                message: 'left',
                system: true,
              })
            }
            if (store.controllerId === msg.userId) {
              const hostId = hostUserId(nextPeers, userId)
              store.setControllerId(hostId)
              if (roleRef.current === 'host') {
                channelRef.current?.send({
                  type: 'pass-control',
                  roomCode,
                  userId,
                  controllerId: hostId,
                })
              }
            }
            break
          }
          case 'pass-control': {
            store.setControllerId(msg.controllerId)
            controllerIdRef.current = msg.controllerId
            const who =
              store.peers.find((p) => p.userId === msg.controllerId)?.displayName || 'Someone'
            store.addChat({
              userId: msg.controllerId,
              displayName: who,
              message: 'has control',
              system: true,
            })
            // Room host echoes so every peer converges on the same controller.
            if (roleRef.current === 'host' && channelRef.current && handleRef.current) {
              const h = handleRef.current
              channelRef.current.send({
                type: 'status',
                roomCode,
                userId,
                displayName: usePartyStore.getState().displayName || 'Viewer',
                isHost: true,
                contentId: h.contentId,
                title: h.title,
                ready: selfReadyRef.current,
                provider: h.getProvider?.() || null,
                controllerId: msg.controllerId,
              })
            }
            break
          }
          case 'control': {
            const active = store.controllerId
            const allowed =
              msg.userId === active ||
              (!active && msg.userId === hostUserId(store.peers, msg.userId))
            if (!allowed || !h) break
            if (msg.action === 'seek' && msg.time != null) {
              applyPlayer({ isPlaying: h.getState().isPlaying, time: msg.time }, true)
            } else if (msg.action === 'play') {
              applyPlayer({ isPlaying: true, time: msg.time ?? h.getState().time }, true)
            } else if (msg.action === 'pause') {
              applyPlayer({ isPlaying: false, time: msg.time ?? h.getState().time }, true)
            }
            break
          }
        }
      },
      {
        onOpen: () => {
          catchUpUntilRef.current = Date.now() + 12_000
          sendPresence('join')
        },
      },
    )

    channelRef.current = channel
    sendPresence('join')
    {
      const store = usePartyStore.getState()
      store.addChat({
        userId,
        displayName: store.displayName || 'Viewer',
        message: 'joined',
        self: true,
        system: true,
      })
    }

    const interval = window.setInterval(() => {
      sendPresence('status')
      // Keep re-applying catch-up until the local player exists / locks on
      if (
        Date.now() < catchUpUntilRef.current &&
        pendingPlayerRef.current &&
        !isControllerNow()
      ) {
        applyPlayer(pendingPlayerRef.current, true)
      }
    }, 2000)

    return () => {
      try {
        channel.send({ type: 'leave', roomCode, userId })
      } catch {
        /* ignore */
      }
      window.clearInterval(interval)
      channel.close()
      channelRef.current = null
    }
  }, [enabled, roomCode, role, userId, handle?.contentId])

  useEffect(() => {
    if (!enabled || !roomCode || !channelRef.current || !handle) return
    const store = usePartyStore.getState()
    const isController = holdingControl({ ...store, role })
    channelRef.current.send({
      type: 'status',
      roomCode,
      userId,
      displayName: displayName || 'Viewer',
      isHost: role === 'host',
      contentId: handle.contentId,
      title: handle.title,
      ready: selfReady,
      provider: role === 'host' ? handle.getProvider?.() || null : null,
      player: isController ? handle.getState() : undefined,
      controllerId: role === 'host' ? store.controllerId || userId : undefined,
    })
    // When guest becomes ready, force one more catch-up from last known controller state
    if (selfReady && pendingPlayerRef.current && !isController) {
      const h = handleRef.current
      if (h) {
        h.applyHostState(pendingPlayerRef.current)
      }
    }
  }, [selfReady, displayName, controllerId, enabled, roomCode, userId, role, handle?.contentId])

  const sendChat = (message: string) => {
    if (!roomCode || !channelRef.current) return
    const at = Date.now()
    const name = usePartyStore.getState().displayName || 'Viewer'
    usePartyStore.getState().addChat({
      userId,
      displayName: name,
      message,
      at,
      self: true,
    })
    channelRef.current.send({
      type: 'chat',
      roomCode,
      userId,
      displayName: name,
      message,
      at,
    })
  }

  const sendTransport = (action: 'play' | 'pause' | 'seek', time?: number) => {
    if (!roomCode || !channelRef.current) return
    const store = usePartyStore.getState()
    if (!holdingControl({ ...store, role })) return
    const t = time ?? handleRef.current?.getState().time ?? 0
    lastAppliedPlayerRef.current = {
      isPlaying:
        action === 'play' ? true : action === 'pause' ? false : lastAppliedPlayerRef.current.isPlaying,
      time: t,
    }
    pendingPlayerRef.current = lastAppliedPlayerRef.current
    channelRef.current.send({
      type: 'control',
      roomCode,
      userId,
      action,
      time: t,
    })

    if (action === 'play' || action === 'pause') {
      const name = store.displayName || 'Viewer'
      const label = action === 'play' ? 'Played' : 'Paused'
      const at = Date.now()
      store.addChat({
        userId,
        displayName: name,
        message: label,
        at,
        self: true,
        system: true,
      })
      channelRef.current.send({
        type: 'chat',
        roomCode,
        userId,
        displayName: name,
        message: label,
        at,
        system: true,
      })
    }
  }

  const passControl = (nextControllerId: string) => {
    if (!roomCode || !channelRef.current) return
    const store = usePartyStore.getState()
    const isHost = role === 'host'
    const holding = holdingControl({ ...store, role })
    if (!isHost && !holding) return
    store.setControllerId(nextControllerId)
    controllerIdRef.current = nextControllerId
    channelRef.current.send({
      type: 'pass-control',
      roomCode,
      userId,
      controllerId: nextControllerId,
    })
    // Host re-asserts authority immediately so guest heartbeats can't race it.
    if (isHost && handleRef.current) {
      const h = handleRef.current
      channelRef.current.send({
        type: 'status',
        roomCode,
        userId,
        displayName: store.displayName || 'Viewer',
        isHost: true,
        contentId: h.contentId,
        title: h.title,
        ready: selfReadyRef.current,
        provider: h.getProvider?.() || null,
        controllerId: nextControllerId,
      })
    }
    const who =
      store.peers.find((p) => p.userId === nextControllerId)?.displayName ||
      (nextControllerId === userId ? store.displayName : 'Someone')
    const at = Date.now()
    store.addChat({
      userId: nextControllerId,
      displayName: who || 'Someone',
      message: 'has control',
      at,
      self: nextControllerId === userId,
      system: true,
    })
  }

  const isController =
    controllerId === userId || (!controllerId && role === 'host')

  return { sendChat, sendTransport, passControl, isController }
}
