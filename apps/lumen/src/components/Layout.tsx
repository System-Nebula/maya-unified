import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { OpenRoomsDock } from './OpenRoomsDock'
import { PartyDock } from './PartyDock'
import { QuickSearch } from './QuickSearch'

const navClass = ({ isActive }: { isActive: boolean }) =>
  [
    'rounded-lg px-3 py-1.5 text-sm font-medium transition',
    isActive ? 'bg-white/10 text-white' : 'text-text-muted hover:bg-white/5 hover:text-white',
  ].join(' ')

export function Layout() {
  const location = useLocation()
  const onWatch = location.pathname.startsWith('/watch')

  return (
    <div className={['relative bg-bg text-text', onWatch ? 'h-screen overflow-hidden' : 'min-h-screen'].join(' ')}>
      {onWatch ? null : (
        <header className="sticky top-0 z-50 border-b border-white/5 bg-bg/80 backdrop-blur-md">
          <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-3 md:gap-4 md:px-6">
            <Link to="/" className="shrink-0 text-lg font-bold tracking-tight text-accent">
              Lumen
            </Link>
            <nav className="hidden items-center gap-1 sm:flex">
              <NavLink to="/" end className={navClass}>
                Home
              </NavLink>
              <NavLink to="/search" className={navClass}>
                Library
              </NavLink>
              <NavLink to="/settings" className={navClass}>
                Settings
              </NavLink>
            </nav>
            <QuickSearch />
            <OpenRoomsDock />
            <PartyDock variant="nav" />
          </div>
        </header>
      )}
      <Outlet />
      {onWatch ? null : (
        <footer className="mx-auto max-w-6xl px-4 py-10 text-center text-xs text-text-dim md:px-6">
          Lumen — TMDB search, provider race, proxied playback. Run with npm run share.
        </footer>
      )}
    </div>
  )
}
