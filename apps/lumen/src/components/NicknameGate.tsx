import { useState, type FormEvent } from 'react'
import { usePartyStore } from '../stores/party'

interface Props {
  title?: string | null
  hostName?: string | null
  onConfirm: (nickname: string) => void
  onCancel?: () => void
}

export function NicknameGate({ title, hostName, onConfirm, onCancel }: Props) {
  const saved = usePartyStore((s) => s.displayName)
  const [name, setName] = useState(saved || '')

  const submit = (e?: FormEvent) => {
    e?.preventDefault?.()
    const nick = name.trim()
    if (!nick) return
    onConfirm(nick)
  }

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
      <form
        onSubmit={submit}
        className="w-full max-w-md rounded-2xl border border-white/10 bg-bg-elevated p-6 shadow-2xl"
      >
        <h2 className="text-xl font-semibold text-white">Join watch party</h2>
        <p className="mt-2 text-sm text-text-muted">
          {hostName ? `${hostName} invited you` : 'Enter a nickname to join'}
          {title ? (
            <>
              {' '}
              for <span className="text-white">{title}</span>
            </>
          ) : (
            '.'
          )}
        </p>
        <label className="mt-5 block space-y-1 text-sm">
          <span className="text-xs text-text-dim">Nickname</span>
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Your name"
            className="w-full rounded-xl border border-white/10 bg-bg-pill px-3 py-2.5 text-white outline-none focus:ring-2 focus:ring-accent/40"
          />
        </label>
        <div className="mt-5 flex gap-2">
          {onCancel ? (
            <button
              type="button"
              onClick={onCancel}
              className="rounded-xl border border-white/10 px-4 py-2.5 text-sm text-text-muted hover:bg-white/5"
            >
              Cancel
            </button>
          ) : null}
          <button
            type="submit"
            disabled={!name.trim()}
            className="flex-1 rounded-xl bg-white py-2.5 text-sm font-semibold text-black hover:bg-white/90 disabled:opacity-40"
          >
            Join party
          </button>
        </div>
      </form>
    </div>
  )
}
