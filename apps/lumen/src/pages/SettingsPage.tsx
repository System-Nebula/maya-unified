import { useEffect, useState } from 'react'
import { usePartyStore } from '../stores/party'

export function SettingsPage() {
  const displayName = usePartyStore((s) => s.displayName)
  const setDisplayName = usePartyStore((s) => s.setDisplayName)
  const showOverlay = usePartyStore((s) => s.showOverlay)
  const setShowOverlay = usePartyStore((s) => s.setShowOverlay)
  const [lab, setLab] = useState('Checking lab…')

  useEffect(() => {
    fetch('/api/providers?all=1')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data) => {
        const t = data.totals || {}
        setLab(
          `Online · ${t.enabledMovieSources ?? '?'} enabled movie · ${t.allMovieSources ?? '?'} all movie · ${t.embeds ?? '?'} embeds`,
        )
      })
      .catch(() => setLab('Offline — start with npm run lab (or npm run dev:all)'))
  }, [])

  return (
    <div className="mx-auto max-w-2xl px-4 py-10 md:px-6">
      <h1 className="text-2xl font-bold">Settings</h1>
      <p className="mt-1 text-sm text-text-muted">
        Local preferences plus scraper lab status. TMDB key lives in <code>lab/.env</code>.
      </p>

      <section className="mt-8 space-y-4 rounded-2xl border border-white/10 bg-bg-elevated p-5">
        <h2 className="font-semibold">Profile</h2>
        <label className="block space-y-1 text-sm">
          <span className="text-text-dim">Display name (watch party)</span>
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            className="w-full rounded-xl border border-white/10 bg-bg-pill px-3 py-2 outline-none focus:ring-2 focus:ring-accent/40"
          />
        </label>
        <label className="flex items-center justify-between text-sm text-text-muted">
          Show party status overlay
          <input
            type="checkbox"
            checked={showOverlay}
            onChange={(e) => setShowOverlay(e.target.checked)}
          />
        </label>
      </section>

      <section className="mt-6 space-y-2 rounded-2xl border border-white/10 bg-bg-elevated p-5 text-sm text-text-muted">
        <h2 className="font-semibold text-white">Scraper lab</h2>
        <p>{lab}</p>
        <ul className="mt-3 list-inside list-disc space-y-1">
          <li>
            Backend: <code className="text-accent">lab/server.mjs</code> (port 3847)
          </li>
          <li>
            Providers: <code className="text-accent">lab/scrapers.js</code>
          </li>
          <li>
            Dev: <code className="text-accent">npm run dev:all</code> (lab + Vite, proxied{' '}
            <code>/api</code>)
          </li>
        </ul>
      </section>
    </div>
  )
}
