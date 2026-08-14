import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { partyInviteUrl } from '../api/lab'
import { copyText } from '../lib/clipboard'
import { usePartyStore } from '../stores/party'

interface Props {
  contentId: string
  title?: string
  onSendChat: (message: string) => void
  onPassControl?: (userId: string) => void
  compact?: boolean
}

export function PartyPanel({ contentId, title, onSendChat, onPassControl, compact }: Props) {
  const watchBase = '/watch'
  const enabled = usePartyStore((s) => s.enabled)
  const roomCode = usePartyStore((s) => s.roomCode)
  const role = usePartyStore((s) => s.role)
  const peers = usePartyStore((s) => s.peers)
  const chat = usePartyStore((s) => s.chat)
  const displayName = usePartyStore((s) => s.displayName)
  const userId = usePartyStore((s) => s.userId)
  const selfReady = usePartyStore((s) => s.selfReady)
  const controllerId = usePartyStore((s) => s.controllerId)
  const showOverlay = usePartyStore((s) => s.showOverlay)
  const enableAsHost = usePartyStore((s) => s.enableAsHost)
  const leave = usePartyStore((s) => s.leave)
  const setShowOverlay = usePartyStore((s) => s.setShowOverlay)
  const setDisplayName = usePartyStore((s) => s.setDisplayName)
  const setPendingInvite = usePartyStore((s) => s.setPendingInvite)
  const setNicknameNeeded = usePartyStore((s) => s.setNicknameNeeded)

  const [chatInput, setChatInput] = useState('')
  const [nameDraft, setNameDraft] = useState(displayName)
  const [copied, setCopied] = useState<'code' | 'link' | 'both' | null>(null)
  const [joinCode, setJoinCode] = useState('')

  const inviteLink = useMemo(() => {
    if (!roomCode) return ''
    return partyInviteUrl(contentId, roomCode, watchBase)
  }, [contentId, roomCode, watchBase])

  const flash = (kind: 'code' | 'link' | 'both') => {
    setCopied(kind)
    window.setTimeout(() => setCopied(null), 1600)
  }

  // Auto-copy code + link when hosting starts
  useEffect(() => {
    if (!enabled || role !== 'host' || !roomCode || !inviteLink) return
    const key = `lumen-copied-${roomCode}`
    if (sessionStorage.getItem(key)) return
    void copyText(`Party code: ${roomCode}\n${inviteLink}`).then((ok) => {
      if (!ok) return
      sessionStorage.setItem(key, '1')
      flash('both')
    })
  }, [enabled, role, roomCode, inviteLink])

  const copyCode = async () => {
    if (!roomCode) return
    if (await copyText(roomCode)) flash('code')
  }

  const copyLink = async () => {
    if (!inviteLink) return
    if (await copyText(inviteLink)) flash('link')
  }

  const onChat = (e: FormEvent) => {
    e.preventDefault()
    const msg = chatInput.trim()
    if (!msg) return
    onSendChat(msg)
    setChatInput('')
  }

  if (!enabled) {
    return (
      <div className="space-y-3 p-1 text-sm">
        <h2 className="text-base font-semibold text-white">Watch party</h2>
        <p className="text-text-muted">
          Host to get a code + link (auto-copied). Friends join with a nickname and land on the same
          title + provider.
        </p>
        <label className="block space-y-1">
          <span className="text-xs text-text-dim">Your nickname</span>
          <input
            value={nameDraft}
            onChange={(e) => setNameDraft(e.target.value)}
            onBlur={() => setDisplayName(nameDraft)}
            className="w-full rounded-lg border border-white/10 bg-bg-pill px-3 py-2 text-white outline-none focus:ring-2 focus:ring-accent/40"
          />
        </label>
        <button
          type="button"
          onClick={() => {
            setDisplayName(nameDraft || 'Host')
            enableAsHost(contentId)
          }}
          className="w-full rounded-xl bg-white py-2.5 font-semibold text-black transition hover:bg-white/90"
        >
          Host a party
        </button>
        <div className="flex gap-2">
          <input
            value={joinCode}
            onChange={(e) => setJoinCode(e.target.value.replace(/\D/g, '').slice(0, 4))}
            placeholder="Code"
            className="w-24 rounded-xl border border-white/10 bg-bg-pill px-3 py-2 text-center tracking-widest text-white outline-none focus:ring-2 focus:ring-accent/40"
          />
          <button
            type="button"
            disabled={joinCode.length < 4}
            onClick={() => {
              setPendingInvite(joinCode)
              setNicknameNeeded(true)
            }}
            className="flex-1 rounded-xl bg-accent-deep py-2.5 font-semibold text-white transition hover:bg-accent disabled:opacity-40"
          >
            Join…
          </button>
        </div>
      </div>
    )
  }

  return (
    <div
      className={[
        'flex flex-col gap-3 p-1 text-sm',
        compact ? 'max-h-[70vh]' : 'h-full max-h-[32rem]',
      ].join(' ')}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-white">Watch party</h2>
          <p className="text-text-muted">
            {role === 'host' ? 'You are the host' : 'Connected as guest'}
            {title ? ` · ${title}` : ''}
          </p>
          {copied === 'both' ? (
            <p className="mt-1 text-xs text-accent">Invite code + link copied</p>
          ) : null}
        </div>
        <button
          type="button"
          onClick={leave}
          className="rounded-lg px-2 py-1 text-xs text-danger hover:bg-danger/10"
        >
          Leave
        </button>
      </div>

      <div className="space-y-2 rounded-xl border border-white/10 bg-bg-pill p-3">
        <div className="flex items-center gap-2">
          <div>
            <div className="text-xs text-text-dim">Invite code</div>
            <div className="font-mono text-2xl tracking-[0.35em] text-accent">{roomCode}</div>
          </div>
          <button
            type="button"
            onClick={() => void copyCode()}
            className="ml-auto rounded-lg bg-white/10 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-white/15"
          >
            {copied === 'code' ? 'Copied' : 'Copy code'}
          </button>
        </div>
        <div className="text-xs text-text-dim">Invite link</div>
        <div className="flex items-center gap-2">
          <input
            readOnly
            value={inviteLink}
            className="min-w-0 flex-1 truncate rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-[11px] text-text-muted"
          />
          <button
            type="button"
            onClick={() => void copyLink()}
            className="shrink-0 rounded-lg bg-white/10 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-white/15"
          >
            {copied === 'link' ? 'Copied' : 'Copy link'}
          </button>
        </div>
      </div>

      <div>
        <div className="mb-1 text-xs text-text-dim">
          Viewers ({peers.length}) ·{' '}
          {
            peers.filter((p) => (p.userId === userId ? selfReady : p.ready)).length
          }{' '}
          ready
        </div>
        <ul className="space-y-1">
          {peers.map((p) => {
            const peerReady = p.userId === userId ? selfReady : p.ready
            const hasControl = (controllerId || peers.find((x) => x.isHost)?.userId) === p.userId
            const iAmController =
              controllerId === userId || (!controllerId && role === 'host')
            const canPass = (role === 'host' || iAmController) && !hasControl && onPassControl
            return (
              <li
                key={p.userId}
                className="flex items-center justify-between gap-2 rounded-lg bg-bg-pill px-2 py-1.5"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <span
                    className={[
                      'inline-block h-2 w-2 shrink-0 rounded-full',
                      peerReady ? 'bg-emerald-400' : 'bg-amber-400/80',
                    ].join(' ')}
                    title={peerReady ? 'Ready' : 'Loading'}
                  />
                  <span className="truncate">{p.displayName}</span>
                </span>
                <span className="flex shrink-0 items-center gap-1.5 text-[10px] uppercase tracking-wide">
                  {hasControl ? <span className="text-accent">Control</span> : null}
                  {p.isHost ? <span className="text-text-dim">Host</span> : null}
                  {canPass ? (
                    <button
                      type="button"
                      onClick={() => onPassControl(p.userId)}
                      className="rounded bg-white/10 px-1.5 py-0.5 normal-case tracking-normal text-white hover:bg-white/15"
                    >
                      Pass
                    </button>
                  ) : null}
                </span>
              </li>
            )
          })}
        </ul>
        <p className="mt-2 text-[11px] text-text-dim">
          Whoever has <span className="text-accent">Control</span> drives play, pause, and seek for
          everyone.
        </p>
      </div>

      <label className="flex items-center justify-between gap-2 text-xs text-text-muted">
        Status overlay
        <input
          type="checkbox"
          checked={showOverlay}
          onChange={(e) => setShowOverlay(e.target.checked)}
        />
      </label>

      <div className="flex min-h-0 flex-1 flex-col rounded-xl border border-white/10 bg-bg-pill">
        <div className="max-h-40 flex-1 space-y-2 overflow-y-auto p-2">
          {chat.length === 0 ? (
            <p className="text-xs text-text-dim">No messages yet</p>
          ) : (
            chat.map((m) => (
              <div key={m.id} className={m.self ? 'text-right' : ''}>
                <div className="text-[10px] text-text-dim">{m.displayName}</div>
                <div
                  className={[
                    'inline-block max-w-[90%] rounded-lg px-2 py-1 text-xs',
                    m.self ? 'bg-accent-deep text-white' : 'bg-bg-hover text-white',
                  ].join(' ')}
                >
                  {m.message}
                </div>
              </div>
            ))
          )}
        </div>
        <form onSubmit={onChat} className="flex border-t border-white/10">
          <input
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            placeholder="Message…"
            className="min-w-0 flex-1 bg-transparent px-3 py-2 text-xs outline-none"
          />
          <button type="submit" className="px-3 text-xs font-semibold text-accent">
            Send
          </button>
        </form>
      </div>
    </div>
  )
}
