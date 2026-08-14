import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { localizeStream, type LabStream } from '../api/lab'

export type PartyRole = 'host' | 'guest' | null

export interface PartyChatMessage {
  id: string
  userId: string
  displayName: string
  message: string
  at: number
  self?: boolean
  /** play/pause/join notices — styled differently from normal chat */
  system?: boolean
}

export interface PartyPeer {
  userId: string
  displayName: string
  isHost: boolean
  ready: boolean
  lastUpdate: number
}

interface PartyState {
  enabled: boolean
  roomCode: string | null
  role: PartyRole
  displayName: string
  userId: string
  showOverlay: boolean
  peers: PartyPeer[]
  chat: PartyChatMessage[]
  contentId: string | null
  hostStream: LabStream | null
  selfReady: boolean
  panelOpen: boolean
  pendingInvite: string | null
  nicknameNeeded: boolean
  /** userId of whoever drives play/pause/seek for the room */
  controllerId: string | null

  enableAsHost: (contentId: string) => string
  enableAsGuest: (roomCode: string, contentId: string) => void
  setContentId: (id: string | null) => void
  setPeers: (peers: PartyPeer[]) => void
  upsertPeer: (peer: PartyPeer) => void
  addChat: (
    msg: Omit<PartyChatMessage, 'id' | 'at'> & { at?: number; system?: boolean },
  ) => void
  setControllerId: (id: string | null) => void
  setShowOverlay: (v: boolean) => void
  setDisplayName: (name: string) => void
  setHostStream: (stream: LabStream | null) => void
  setSelfReady: (ready: boolean) => void
  setPanelOpen: (open: boolean) => void
  setPendingInvite: (code: string | null) => void
  setNicknameNeeded: (needed: boolean) => void
  leave: () => void
}

function makeCode() {
  return String(Math.floor(1000 + Math.random() * 9000))
}

function makeUserId() {
  const existing = localStorage.getItem('lumen-user-id')
  if (existing) return existing
  const id = `u_${Math.random().toString(36).slice(2, 10)}`
  localStorage.setItem('lumen-user-id', id)
  return id
}

export const usePartyStore = create<PartyState>()(
  persist(
    (set, get) => ({
      enabled: false,
      roomCode: null,
      role: null,
      displayName: '',
      userId: makeUserId(),
      showOverlay: true,
      peers: [],
      chat: [],
      contentId: null,
      hostStream: null,
      selfReady: false,
      panelOpen: false,
      pendingInvite: null,
      nicknameNeeded: false,
      controllerId: null,

      enableAsHost: (contentId) => {
        const { userId, displayName } = get()
        const roomCode = makeCode()
        set({
          enabled: true,
          roomCode,
          role: 'host',
          contentId,
          chat: [],
          hostStream: null,
          selfReady: false,
          panelOpen: true,
          controllerId: userId,
          peers: [
            {
              userId,
              displayName: displayName || 'Host',
              isHost: true,
              ready: false,
              lastUpdate: Date.now(),
            },
          ],
        })
        return roomCode
      },

      enableAsGuest: (roomCode, contentId) => {
        const { userId, displayName } = get()
        set({
          enabled: true,
          roomCode: roomCode.trim().toUpperCase(),
          role: 'guest',
          contentId,
          chat: [],
          selfReady: false,
          panelOpen: true,
          nicknameNeeded: false,
          pendingInvite: null,
          controllerId: null,
          peers: [
            {
              userId,
              displayName: displayName || 'Guest',
              isHost: false,
              ready: false,
              lastUpdate: Date.now(),
            },
          ],
        })
      },

      setContentId: (id) => set({ contentId: id }),
      setPeers: (peers) => set({ peers }),
      upsertPeer: (peer) =>
        set((s) => {
          const peers = [...s.peers]
          const idx = peers.findIndex((p) => p.userId === peer.userId)
          if (idx >= 0) peers[idx] = { ...peers[idx], ...peer, lastUpdate: Date.now() }
          else peers.push({ ...peer, lastUpdate: Date.now() })
          return { peers }
        }),
      addChat: (msg) =>
        set((s) => ({
          chat: [
            ...s.chat,
            {
              id: `${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
              at: msg.at ?? Date.now(),
              userId: msg.userId,
              displayName: msg.displayName,
              message: msg.message,
              self: msg.self,
              system: msg.system,
            },
          ].slice(-200),
        })),
      setControllerId: (id) => set({ controllerId: id }),
      setShowOverlay: (v) => set({ showOverlay: v }),
      setDisplayName: (name) => set({ displayName: name.trim() || 'Viewer' }),
      setHostStream: (stream) => set({ hostStream: stream ? localizeStream(stream) : null }),
      setSelfReady: (ready) =>
        set((s) => {
          const self = s.peers.find((p) => p.userId === s.userId)
          if (s.selfReady === ready && self?.ready === ready) return s
          return {
            selfReady: ready,
            peers: s.peers.map((p) =>
              p.userId === s.userId ? { ...p, ready, lastUpdate: Date.now() } : p,
            ),
          }
        }),
      setPanelOpen: (open) => set({ panelOpen: open }),
      setPendingInvite: (code) => set({ pendingInvite: code }),
      setNicknameNeeded: (needed) => set({ nicknameNeeded: needed }),
      leave: () =>
        set({
          enabled: false,
          roomCode: null,
          role: null,
          peers: [],
          chat: [],
          contentId: null,
          hostStream: null,
          selfReady: false,
          panelOpen: false,
          pendingInvite: null,
          nicknameNeeded: false,
          controllerId: null,
        }),
    }),
    {
      name: 'lumen-party',
      partialize: (s) => ({
        displayName: s.displayName,
        userId: s.userId,
        showOverlay: s.showOverlay,
      }),
    },
  ),
)
