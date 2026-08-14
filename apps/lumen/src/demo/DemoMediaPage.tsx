import { useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

/** /media/:id → archive with details pop-out */
export function DemoMediaPage() {
  const { id } = useParams()
  const navigate = useNavigate()

  useEffect(() => {
    if (!id) {
      navigate('/', { replace: true })
      return
    }
    navigate(`/?details=${encodeURIComponent(id)}`, { replace: true })
  }, [id, navigate])

  return (
    <div className="demo-media-empty">
      <p className="demo-status">Opening details…</p>
    </div>
  )
}
