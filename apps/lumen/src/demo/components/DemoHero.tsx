import { cacheTitle, type LabDetails } from '../../api/lab'
import { useDemoDetails } from '../DemoDetailsContext'

interface Props {
  featured: LabDetails
}

export function DemoHero({ featured }: Props) {
  const { openDetails } = useDemoDetails()
  const art = featured.backdrop || featured.poster

  return (
    <section className="demo-hero">
      <div className="demo-hero-media" aria-hidden>
        {art ? <img src={art} alt="" /> : null}
        <div className="demo-hero-scrim" />
      </div>
      <div className="demo-hero-body">
        <p className="demo-display demo-hero-brand">CINEMAYA</p>
        <p className="demo-hero-tag">A million films built for friends</p>
        <p className="demo-hero-support">
          {featured.title}
          {featured.releaseYear ? ` · ${featured.releaseYear}` : ''}. Discover, race every source,
          watch together.
        </p>
        <div className="demo-hero-ctas">
          <button
            type="button"
            className="demo-btn demo-btn-primary"
            onClick={() => {
              cacheTitle(featured)
              openDetails(featured, { autoWatch: true })
            }}
          >
            Watch
          </button>
          <button
            type="button"
            className="demo-btn demo-btn-ghost"
            onClick={() => {
              cacheTitle(featured)
              openDetails(featured)
            }}
          >
            Details
          </button>
        </div>
      </div>
    </section>
  )
}
