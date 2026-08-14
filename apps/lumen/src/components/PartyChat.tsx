import { useEffect, useRef, useState, type FormEvent } from 'react'
import { usePartyStore } from '../stores/party'

interface Props {
  onSend: (message: string) => void
  className?: string
}

export function PartyChat({ onSend, className }: Props) {
  const chat = usePartyStore((s) => s.chat)
  const roomCode = usePartyStore((s) => s.roomCode)
  const peers = usePartyStore((s) => s.peers)
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chat.length])

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    const msg = input.trim()
    if (!msg) return
    onSend(msg)
    setInput('')
  }

  return (
    <div className={['flex min-h-0 flex-col', className].filter(Boolean).join(' ')}>
      <div className="shrink-0 border-b border-white/10 px-3 py-2">
        <div className="text-xs font-semibold uppercase tracking-wide text-text-dim">Chat</div>
        <div className="truncate text-sm text-white">
          Room {roomCode}
          <span className="text-text-dim"> · {peers.length} watching</span>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-3 py-2">
        {chat.length === 0 ? (
          <p className="py-6 text-center text-xs text-text-dim">Say hi — messages sync live.</p>
        ) : (
          chat.map((m) =>
            m.system ? (
              <div key={m.id} className="py-0.5 text-center text-[11px] text-text-dim">
                <span className="font-medium text-text-muted">{m.displayName}</span>{' '}
                {m.message}
              </div>
            ) : (
              <div key={m.id} className={m.self ? 'text-right' : ''}>
                <div className="text-[10px] text-text-dim">{m.displayName}</div>
                <div
                  className={[
                    'inline-block max-w-[90%] rounded-lg px-2.5 py-1.5 text-xs',
                    m.self ? 'bg-accent-deep text-white' : 'bg-white/10 text-white',
                  ].join(' ')}
                >
                  {m.message}
                </div>
              </div>
            ),
          )
        )}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={onSubmit} className="flex shrink-0 border-t border-white/10">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Message…"
          className="min-w-0 flex-1 bg-transparent px-3 py-2.5 text-sm text-white outline-none placeholder:text-text-dim"
        />
        <button
          type="submit"
          disabled={!input.trim()}
          className="px-3 text-sm font-semibold text-accent disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </div>
  )
}
