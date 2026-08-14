import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { DemoLayout } from './demo/DemoLayout'
import { DemoHomePage } from './demo/DemoHomePage'
import { DemoCatalogPage } from './demo/DemoCatalogPage'
import { DemoSearchPage } from './demo/DemoSearchPage'
import { DemoMediaPage } from './demo/DemoMediaPage'
import { DemoRoomsPage } from './demo/DemoRoomsPage'
import { DemoWatchPage } from './demo/DemoWatchPage'

function DemoLegacyRedirect() {
  const location = useLocation()
  const rest = location.pathname.replace(/^\/demo\/?/, '/') || '/'
  const path = rest === '//' ? '/' : rest.startsWith('/') ? rest : `/${rest}`
  return <Navigate to={`${path}${location.search}${location.hash}`} replace />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<DemoLayout />}>
          <Route index element={<DemoHomePage />} />
          <Route path="movies" element={<DemoCatalogPage kind="movies" />} />
          <Route path="tv" element={<DemoCatalogPage kind="tv" />} />
          <Route path="anime" element={<DemoCatalogPage kind="anime" />} />
          <Route path="search" element={<DemoSearchPage />} />
          <Route path="rooms" element={<DemoRoomsPage />} />
          <Route path="media/:id" element={<DemoMediaPage />} />
          <Route path="watch/:id" element={<DemoWatchPage />} />
        </Route>
        <Route path="demo/*" element={<DemoLegacyRedirect />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
