import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { lookupPartyRoom, partyInviteUrl, watchUrl } from '../api/lab'
import { copyText } from '../lib/clipboard'
import { usePartyStore } from '../stores/party'
import { NicknameGate } from './NicknameGate'
import { PartyPanel } from './PartyPanel'

interface Props {
  /** Content id when already on a title page; optional for nav browse mode */
  contentId?: string
  title?: string
  onSendChat?: (message: string) => void
  onPassControl?: (userId: string) => void
  variant?: 'nav' | 'watch'
}

export function PartyDock({ contentId, title, onSendChat, onPassControl, variant = 'nav' }: Props) {
  const navigate = useNavigate()
  const watchBase = '/watch'
  const enabled = usePartyStore((s) => s.enabled)
  const roomCode = usePartyStore((s) => s.roomCode)
  const peers = usePartyStore((s) => s.peers)
  const userId = usePartyStore((s) => s.userId)
  const selfReady = usePartyStore((s) => s.selfReady)
  const panelOpen = usePartyStore((s) => s.panelOpen)
  const setPanelOpen = usePartyStore((s) => s.setPanelOpen)
  const pendingInvite = usePartyStore((s) => s.pendingInvite)
  const nicknameNeeded = usePartyStore((s) => s.nicknameNeeded)
  const setPendingInvite = usePartyStore((s) => s.setPendingInvite)
  const setNicknameNeeded = usePartyStore((s) => s.setNicknameNeeded)
  const setDisplayName = usePartyStore((s) => s.setDisplayName)
  const enableAsGuest = usePartyStore((s) => s.enableAsGuest)
  const partyContentId = usePartyStore((s) => s.contentId)
  const setHostStream = usePartyStore((s) => s.setHostStream)
  const [inviteMeta, setInviteMeta] = useState<{ title?: string | null; hostName?: string | null }>(
    {},
  )
  const [joinCode, setJoinCode] = useState('')
  const rootRef = useRef<HTMLDivElement>(null)

  const readyCount = peers.filter((p) =>
    p.userId === userId ? selfReady : p.ready,
  ).length
  const activeContent = contentId || partyContentId

  useEffect(() => {
    if (!panelOpen) return
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setPanelOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [panelOpen, setPanelOpen])

  useEffect(() => {
    if (!pendingInvite || !nicknameNeeded) return
    lookupPartyRoom(pendingInvite)
      .then((room) => setInviteMeta({ title: room.title, hostName: room.hostName }))
      .catch(() => setInviteMeta({}))
  }, [pendingInvite, nicknameNeeded])

  const completeInviteJoin = async (nickname: string) => {
    const code = pendingInvite
    if (!code) return
    setDisplayName(nickname)
    const room = await lookupPartyRoom(code)
    const target = room.contentId
    if (!target) throw new Error('Host has not opened a title yet')
    if (room.stream?.playable?.url) setHostStream(room.stream)
    enableAsGuest(code, target)
    setNicknameNeeded(false)
    setPendingInvite(null)
    navigate(watchUrl(target, { party: true, room: code, base: watchBase }))
  }

  const startJoinFromDock = () => {
    const code = joinCode.trim()
    if (code.length < 4) return
    setPendingInvite(code)
    setNicknameNeeded(true)
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setPanelOpen(!panelOpen)}
        className={[
          'inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-semibold transition',
          enabled || panelOpen
            ? 'bg-accent-deep text-white'
            : variant === 'watch'
              ? 'bg-white/10 text-white hover:bg-white/15'
              : 'bg-white/5 text-text-muted hover:bg-white/10 hover:text-white',
        ].join(' ')}
      >
        <span>Party</span>
        {enabled && roomCode ? (
          <>
            <span className="font-mono tracking-wider">{roomCode}</span>
            <span className="rounded-full bg-black/30 px-1.5 py-0.5 text-[10px]">
              {readyCount}/{Math.max(peers.length, 1)} ready
            </span>
          </>
        ) : null}
      </button>

      {panelOpen ? (
        <div
          className={[
            'absolute right-0 z-50 mt-2 max-h-[min(80vh,36rem)] w-[min(22rem,calc(100vw-2rem))] overflow-y-auto rounded-2xl border border-white/10 bg-bg-elevated p-3 shadow-2xl',
            variant === 'watch' ? 'top-full' : 'top-full',
          ].join(' ')}
        >
          {enabled && activeContent ? (
            <PartyPanel
              contentId={activeContent}
              title={title}
              onSendChat={onSendChat || (() => {})}
              onPassControl={onPassControl}
              compact
            />
          ) : (
            <div className="space-y-3 p-1 text-sm">
              <h2 className="font-semibold text-white">Watch party</h2>
              <p className="text-text-muted">
                Enter an invite code to join a friend’s room. You’ll pick a nickname next.
              </p>
              <div className="flex gap-2">
                <input
                  value={joinCode}
                  onChange={(e) => setJoinCode(e.target.value.replace(/\D/g, '').slice(0, 4))}
                  placeholder="Code"
                  className="w-28 rounded-xl border border-white/10 bg-bg-pill px-3 py-2 text-center font-mono tracking-[0.3em] text-white outline-none focus:ring-2 focus:ring-accent/40"
                />
                <button
                  type="button"
                  disabled={joinCode.length < 4}
                  onClick={startJoinFromDock}
                  className="flex-1 rounded-xl bg-accent-deep py-2 font-semibold text-white disabled:opacity-40"
                >
                  Continue
                </button>
              </div>
              <p className="text-xs text-text-dim">
                Hosting starts from a title’s player — open a movie and tap Host.
              </p>
            </div>
          )}
        </div>
      ) : null}

      {nicknameNeeded && pendingInvite ? (
        <NicknameGate
          title={inviteMeta.title}
          hostName={inviteMeta.hostName}
          onCancel={() => {
            setNicknameNeeded(false)
            setPendingInvite(null)
          }}
          onConfirm={(nick) => {
            void completeInviteJoin(nick).catch((e: Error) => {
              alert(e.message)
            })
          }}
        />
      ) : null}
    </div>
  )
}

export function copyPartyInvite(contentId: string, roomCode: string) {
  const link = partyInviteUrl(contentId, roomCode)
  return copyText(`${roomCode}\n${link}`)
}
