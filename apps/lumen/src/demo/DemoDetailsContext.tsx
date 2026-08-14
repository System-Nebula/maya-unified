import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  cacheTitle,
  getCachedTitle,
  mediaKey,
  parseMediaKey,
  type LabDetails,
  type LabSearchHit,
} from '../api/lab'

function cachedFromPath(pathId: string): DemoDetailsItem | null {
  try {
    const raw = sessionStorage.getItem(`lumen:title:${pathId}`)
    if (raw) return JSON.parse(raw) as DemoDetailsItem
  } catch {
    /* fall through */
  }
  const parsed = parseMediaKey(pathId)
  return parsed ? getCachedTitle(parsed.tmdbId, parsed.type) : null
}

export type DemoDetailsItem = LabDetails | LabSearchHit

type OpenOpts = {
  autoWatch?: boolean
  party?: boolean
}

type DemoDetailsContextValue = {
  detailsId: string | null
  seed: DemoDetailsItem | null
  autoWatch: boolean
  autoParty: boolean
  openDetails: (item: DemoDetailsItem, opts?: OpenOpts) => void
  openDetailsById: (pathId: string, opts?: OpenOpts) => void
  closeDetails: () => void
  clearAutoWatch: () => void
}

const DemoDetailsContext = createContext<DemoDetailsContextValue | null>(null)

function readUrlDetailsId(search: string) {
  return new URLSearchParams(search).get('details')
}

export function DemoDetailsProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [seed, setSeed] = useState<DemoDetailsItem | null>(null)
  const [autoWatch, setAutoWatch] = useState(false)
  const [autoParty, setAutoParty] = useState(false)

  const detailsId = readUrlDetailsId(location.search)

  const writeDetailsParam = useCallback(
    (pathId: string | null, replace = false) => {
      const params = new URLSearchParams(location.search)
      if (pathId) params.set('details', pathId)
      else params.delete('details')
      const search = params.toString()
      // Don't put details query on the watch player route
      const pathname = location.pathname.includes('/watch/') ? '/' : location.pathname
      navigate({ pathname, search: search ? `?${search}` : '' }, { replace })
    },
    [location.pathname, location.search, navigate],
  )

  // Deep link / refresh: hydrate seed from cache when ?details= is present
  useEffect(() => {
    if (!detailsId) {
      setSeed(null)
      return
    }
    const cached = cachedFromPath(detailsId)
    if (cached) setSeed(cached)
  }, [detailsId])

  const openDetails = useCallback(
    (item: DemoDetailsItem, opts?: OpenOpts) => {
      cacheTitle(item)
      setSeed(item)
      setAutoWatch(!!opts?.autoWatch)
      setAutoParty(!!opts?.party)
      writeDetailsParam(mediaKey(item.title, item.tmdbId, item.type))
    },
    [writeDetailsParam],
  )

  const openDetailsById = useCallback(
    (pathId: string, opts?: OpenOpts) => {
      setSeed(cachedFromPath(pathId))
      setAutoWatch(!!opts?.autoWatch)
      setAutoParty(!!opts?.party)
      writeDetailsParam(pathId)
    },
    [writeDetailsParam],
  )

  const closeDetails = useCallback(() => {
    setAutoWatch(false)
    setAutoParty(false)
    writeDetailsParam(null, true)
  }, [writeDetailsParam])

  const clearAutoWatch = useCallback(() => {
    setAutoWatch(false)
    setAutoParty(false)
  }, [])

  const value = useMemo(
    () => ({
      detailsId,
      seed,
      autoWatch,
      autoParty,
      openDetails,
      openDetailsById,
      closeDetails,
      clearAutoWatch,
    }),
    [
      detailsId,
      seed,
      autoWatch,
      autoParty,
      openDetails,
      openDetailsById,
      closeDetails,
      clearAutoWatch,
    ],
  )

  return <DemoDetailsContext.Provider value={value}>{children}</DemoDetailsContext.Provider>
}

export function useDemoDetails() {
  const ctx = useContext(DemoDetailsContext)
  if (!ctx) throw new Error('useDemoDetails must be used within DemoDetailsProvider')
  return ctx
}
