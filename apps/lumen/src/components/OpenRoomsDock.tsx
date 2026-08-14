import { useEffect, useRef, useState } from 'react'
import { fetchOpenRooms, type OpenPartyRoom } from '../api/lab'
import { usePartyStore } from '../stores/party'

export function OpenRoomsDock() {
  const [open, setOpen] = useState(false)
  const [rooms, setRooms] = useState<OpenPartyRoom[]>([])
  const [loading, setLoading] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  const myRoom = usePartyStore((s) => s.roomCode)
  const setPendingInvite = usePartyStore((s) => s.setPendingInvite)
  const setNicknameNeeded = usePartyStore((s) => s.setNicknameNeeded)
  const setPanelOpen = usePartyStore((s) => s.setPanelOpen)

  const refresh = () => {
    setLoading(true)
    fetchOpenRooms()
      .then(setRooms)
      .catch(() => setRooms([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    refresh()
    const id = window.setInterval(refresh, open ? 4000 : 12000)
    return () => window.clearInterval(id)
  }, [open])

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const joinRoom = (code: string) => {
    if (myRoom && myRoom === code) {
      setOpen(false)
      setPanelOpen(true)
      return
    }
    setPendingInvite(code)
    setNicknameNeeded(true)
    setPanelOpen(true)
    setOpen(false)
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={[
          'inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-semibold transition',
          open
            ? 'bg-white/15 text-white'
            : 'bg-white/5 text-text-muted hover:bg-white/10 hover:text-white',
        ].join(' ')}
      >
        <span>Open Rooms</span>
        {rooms.length > 0 ? (
          <span className="rounded-full bg-accent-deep/80 px-1.5 py-0.5 text-[10px] text-white">
            {rooms.length}
          </span>
        ) : null}
      </button>

      {open ? (
        <div className="absolute right-0 z-50 mt-2 w-[min(22rem,calc(100vw-2rem))] rounded-2xl border border-white/10 bg-bg-elevated p-3 shadow-2xl">
          <div className="mb-2 flex items-center justify-between px-1">
            <h2 className="text-sm font-semibold text-white">Open rooms</h2>
            <button
              type="button"
              onClick={refresh}
              className="text-[11px] text-text-dim hover:text-white"
            >
              {loading ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>

          {rooms.length === 0 ? (
            <p className="px-1 py-6 text-center text-sm text-text-muted">
              No live parties right now.
            </p>
          ) : (
            <ul className="max-h-72 space-y-1 overflow-y-auto">
              {rooms.map((room) => {
                const mine = myRoom === room.roomCode
                return (
                  <li key={room.roomCode}>
                    <button
                      type="button"
                      onClick={() => joinRoom(room.roomCode)}
                      className="flex w-full flex-col gap-0.5 rounded-xl px-3 py-2.5 text-left transition hover:bg-white/5"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-medium text-white">
                          {room.title || 'Untitled title'}
                        </span>
                        <span className="shrink-0 font-mono text-[11px] tracking-wider text-accent">
                          {room.roomCode}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 text-[11px] text-text-dim">
                        <span>{room.hostName ? `Host · ${room.hostName}` : 'Host unknown'}</span>
                        <span>·</span>
                        <span>
                          {room.viewers} {room.viewers === 1 ? 'viewer' : 'viewers'}
                        </span>
                        {mine ? (
                          <>
                            <span>·</span>
                            <span className="text-accent">You</span>
                          </>
                        ) : null}
                      </div>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  )
}
