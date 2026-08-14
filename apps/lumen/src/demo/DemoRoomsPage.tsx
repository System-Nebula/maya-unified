import { FormEvent, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { demoWatchUrl, fetchOpenRooms, lookupPartyRoom, type OpenPartyRoom } from '../api/lab'
import { NicknameGate } from '../components/NicknameGate'
import { usePartyStore } from '../stores/party'

export function DemoRoomsPage() {
  const navigate = useNavigate()
  const [rooms, setRooms] = useState<OpenPartyRoom[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [joinCode, setJoinCode] = useState('')
  const [inviteMeta, setInviteMeta] = useState<{ title?: string | null; hostName?: string | null }>(
    {},
  )

  const myRoom = usePartyStore((s) => s.roomCode)
  const pendingInvite = usePartyStore((s) => s.pendingInvite)
  const nicknameNeeded = usePartyStore((s) => s.nicknameNeeded)
  const setPendingInvite = usePartyStore((s) => s.setPendingInvite)
  const setNicknameNeeded = usePartyStore((s) => s.setNicknameNeeded)
  const setDisplayName = usePartyStore((s) => s.setDisplayName)
  const enableAsGuest = usePartyStore((s) => s.enableAsGuest)
  const setHostStream = usePartyStore((s) => s.setHostStream)
  const setPanelOpen = usePartyStore((s) => s.setPanelOpen)

  const refresh = () => {
    setLoading(true)
    fetchOpenRooms()
      .then((list) => {
        setRooms(list)
        setError('')
      })
      .catch((e: Error) => {
        setRooms([])
        setError(e.message)
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    refresh()
    const id = window.setInterval(refresh, 4000)
    return () => window.clearInterval(id)
  }, [])

  useEffect(() => {
    if (!pendingInvite || !nicknameNeeded) return
    lookupPartyRoom(pendingInvite)
      .then((room) => setInviteMeta({ title: room.title, hostName: room.hostName }))
      .catch(() => setInviteMeta({}))
  }, [pendingInvite, nicknameNeeded])

  const beginJoin = (code: string) => {
    const normalized = code.trim().toUpperCase()
    if (normalized.length < 4) return
    if (myRoom && myRoom === normalized) {
      setPanelOpen(true)
      return
    }
    setPendingInvite(normalized)
    setNicknameNeeded(true)
  }

  const onJoinSubmit = (e: FormEvent) => {
    e.preventDefault()
    beginJoin(joinCode)
  }

  const completeJoin = async (nickname: string) => {
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
    navigate(demoWatchUrl(target, { party: true, room: code }))
  }

  return (
    <div className="demo-rooms-page">
      <header className="demo-rooms-header">
        <div>
          <h1 className="demo-display">Rooms</h1>
          <p className="demo-status">Live watch parties on your Tailscale network.</p>
        </div>
        <button type="button" className="demo-btn demo-btn-ghost" onClick={refresh}>
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </header>

      <form className="demo-rooms-join" onSubmit={onJoinSubmit}>
        <input
          value={joinCode}
          onChange={(e) => setJoinCode(e.target.value.replace(/\D/g, '').slice(0, 4))}
          placeholder="Code"
          inputMode="numeric"
          autoComplete="off"
        />
        <button type="submit" className="demo-btn demo-btn-primary" disabled={joinCode.length < 4}>
          Join room
        </button>
      </form>

      {error ? <p className="demo-error">{error}</p> : null}

      {rooms.length === 0 && !loading ? (
        <p className="demo-rooms-empty">No live parties right now. Start one from any title.</p>
      ) : (
        <ul className="demo-rooms-list">
          {rooms.map((room) => {
            const mine = myRoom === room.roomCode
            return (
              <li key={room.roomCode}>
                <button type="button" className="demo-room-card" onClick={() => beginJoin(room.roomCode)}>
                  <div className="demo-room-card-top">
                    <h2>{room.title || 'Untitled title'}</h2>
                    <span className="demo-room-code">{room.roomCode}</span>
                  </div>
                  <div className="demo-room-card-meta">
                    <span>{room.hostName ? `Host · ${room.hostName}` : 'Host unknown'}</span>
                    <span>
                      {room.viewers} {room.viewers === 1 ? 'viewer' : 'viewers'}
                    </span>
                    {room.hasStream ? <span className="demo-room-live">Live</span> : null}
                    {mine ? <span className="demo-room-you">You</span> : null}
                  </div>
                </button>
              </li>
            )
          })}
        </ul>
      )}

      {nicknameNeeded && pendingInvite ? (
        <NicknameGate
          title={inviteMeta.title}
          hostName={inviteMeta.hostName}
          onCancel={() => {
            setNicknameNeeded(false)
            setPendingInvite(null)
          }}
          onConfirm={(nick) => {
            void completeJoin(nick).catch((e: Error) => alert(e.message))
          }}
        />
      ) : null}
    </div>
  )
}
