import { Link } from 'react-router-dom'

export interface MediaCardItem {
  id: string
  title: string
  year?: number | null
  poster?: string | null
  subtitle?: string
}

export function MediaCard({ item }: { item: MediaCardItem }) {
  return (
    <Link
      to={`/media/${item.id}`}
      className="group relative block overflow-hidden rounded-xl bg-bg-elevated shadow-lg shadow-black/40 transition hover:-translate-y-0.5 hover:ring-1 hover:ring-white/10"
    >
      <div className="aspect-[2/3] overflow-hidden bg-bg-hover">
        {item.poster ? (
          <img
            src={item.poster}
            alt={item.title}
            className="h-full w-full object-cover transition duration-300 group-hover:scale-105"
            loading="lazy"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-bg-hover to-bg px-3 text-center text-sm text-text-muted">
            {item.title}
          </div>
        )}
      </div>
      <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/90 via-black/50 to-transparent p-3 pt-10">
        <h3 className="line-clamp-2 text-sm font-semibold text-white">{item.title}</h3>
        <p className="mt-0.5 text-xs text-text-muted">
          {item.subtitle || (item.year ? String(item.year) : '—')}
        </p>
      </div>
      <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-card-bar opacity-0 transition group-hover:opacity-100">
        <div className="h-full w-1/3 bg-card-bar-fill" />
      </div>
    </Link>
  )
}
