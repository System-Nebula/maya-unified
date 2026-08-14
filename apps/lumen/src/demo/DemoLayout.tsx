import { useEffect } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { OpenRoomsDock } from '../components/OpenRoomsDock'
import { PartyDock } from '../components/PartyDock'
import { installPstreamBridge } from '../lib/pstreamBridge'
import { DemoDetailsProvider } from './DemoDetailsContext'
import { DemoDetailsModal } from './components/DemoDetailsModal'
import { DemoQuickSearch } from './components/DemoQuickSearch'
import './demo.css'

export function DemoLayout() {
  const location = useLocation()
  const onWatch = location.pathname.includes('/watch/')

  useEffect(() => installPstreamBridge(), [])

  return (
    <DemoDetailsProvider>
      <div className={['demo-shell', onWatch ? 'demo-shell-watch' : ''].filter(Boolean).join(' ')}>
        {onWatch ? null : (
          <header className="demo-header">
            <div className="demo-header-inner">
              <Link to="/" className="demo-brand">
                CINEMAYA
              </Link>
              <nav className="demo-nav">
                <NavLink to="/" end>
                  Archive
                </NavLink>
                <NavLink to="/movies">Movies</NavLink>
                <NavLink to="/tv">TV</NavLink>
                <NavLink to="/anime">Anime</NavLink>
                <NavLink to="/search">Search</NavLink>
                <NavLink to="/rooms">Rooms</NavLink>
              </nav>
              <div className="demo-header-actions">
                <DemoQuickSearch />
                <OpenRoomsDock />
                <PartyDock variant="nav" />
              </div>
            </div>
          </header>
        )}

        <div className="demo-shell-body">
          <Outlet />
        </div>

        {onWatch ? null : (
          <footer className="demo-footer">
            <div className="demo-footer-inner">
              <div className="demo-footer-brand">
                <span className="demo-display">CINEMAYA</span>
                <p>A million films built for friends</p>
              </div>
              <nav className="demo-footer-nav">
                <Link to="/">Archive</Link>
                <Link to="/movies">Movies</Link>
                <Link to="/tv">TV</Link>
                <Link to="/anime">Anime</Link>
                <Link to="/search">Search</Link>
                <Link to="/rooms">Rooms</Link>
              </nav>
              <p className="demo-footer-note">
                TMDB discovery · provider race · Tailscale watch parties
              </p>
            </div>
          </footer>
        )}

        {onWatch ? null : <DemoDetailsModal />}
      </div>
    </DemoDetailsProvider>
  )
}
