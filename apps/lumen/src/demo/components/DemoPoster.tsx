import { cacheTitle, mediaKey, type LabDetails, type LabSearchHit } from '../../api/lab'
import { useDemoDetails } from '../DemoDetailsContext'

type Item = LabDetails | LabSearchHit

export function DemoPoster({ item }: { item: Item }) {
  const { openDetails } = useDemoDetails()

  return (
    <button
      type="button"
      className="demo-poster"
      onClick={() => {
        cacheTitle(item)
        openDetails(item)
      }}
    >
      <div className="demo-poster-art">
        {item.poster ? (
          <img src={item.poster} alt="" loading="lazy" />
        ) : (
          <div className="demo-empty-poster">{item.title}</div>
        )}
      </div>
      <div className="demo-poster-meta">
        <div className="demo-poster-title">{item.title}</div>
        <div className="demo-poster-year">
          {item.type === 'show' ? 'TV' : 'Movie'}
          {item.releaseYear ? ` · ${item.releaseYear}` : ''}
        </div>
      </div>
    </button>
  )
}
