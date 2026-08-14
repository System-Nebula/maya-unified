import { useEffect, useRef } from 'react'
import type { LabDetails, LabSearchHit } from '../../api/lab'
import { DemoPoster } from './DemoPoster'

interface Props {
  id?: string
  title: string
  items: Array<LabDetails | LabSearchHit>
}

export function DemoRail({ id, title, items }: Props) {
  const trackRef = useRef<HTMLDivElement>(null)

  // Vertical wheel / trackpad over a row scrolls it sideways (does not steal clicks).
  useEffect(() => {
    const el = trackRef.current
    if (!el) return

    const onWheel = (e: WheelEvent) => {
      const mostlyVertical = Math.abs(e.deltaY) >= Math.abs(e.deltaX)
      const delta = mostlyVertical ? e.deltaY : e.deltaX
      if (!delta) return

      const max = el.scrollWidth - el.clientWidth
      if (max <= 0) return

      const atStart = el.scrollLeft <= 0 && delta < 0
      const atEnd = el.scrollLeft >= max - 1 && delta > 0
      if (atStart || atEnd) return

      e.preventDefault()
      el.scrollLeft += delta
    }

    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [items.length])

  if (!items.length) return null

  return (
    <section className="demo-rail" id={id}>
      <h2 className="demo-rail-title">{title}</h2>
      <div className="demo-rail-fade" aria-hidden />
      <div ref={trackRef} className="demo-rail-track">
        {items.map((item) => (
          <DemoPoster key={`${item.type}-${item.tmdbId}`} item={item} />
        ))}
      </div>
    </section>
  )
}
