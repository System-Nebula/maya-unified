/**
 * Local library catalog. Streams are public sample / demo URLs only.
 * No third-party scrape providers — add your own HLS/MP4 URLs here or via API later.
 */

export type MediaType = 'movie' | 'show'

export interface CatalogItem {
  id: string
  type: MediaType
  title: string
  year: number
  overview: string
  /** Poster / card image */
  poster: string
  /** Backdrop for detail / player chrome */
  backdrop: string
  /** Direct playable URL (HLS m3u8 or progressive MP4) */
  streamUrl: string
  streamKind: 'hls' | 'file'
  runtimeMinutes?: number
  genres: string[]
}

export const catalog: CatalogItem[] = [
  {
    id: 'big-buck-bunny',
    type: 'movie',
    title: 'Big Buck Bunny',
    year: 2008,
    overview:
      'A large and lovable rabbit deals with three tiny bullies, led by a flying squirrel, who are determined to squelch his happiness.',
    poster: 'https://upload.wikimedia.org/wikipedia/commons/thumb/c/c5/Big_buck_bunny_poster_big.jpg/440px-Big_buck_bunny_poster_big.jpg',
    backdrop: 'https://upload.wikimedia.org/wikipedia/commons/thumb/c/c5/Big_buck_bunny_poster_big.jpg/1024px-Big_buck_bunny_poster_big.jpg',
    streamUrl: 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4',
    streamKind: 'file',
    runtimeMinutes: 10,
    genres: ['Animation', 'Comedy'],
  },
  {
    id: 'sintel',
    type: 'movie',
    title: 'Sintel',
    year: 2010,
    overview:
      'A lonely young woman, Sintel, helps and befriends a dragon, whom she calls Scales. But when he is kidnapped by an adult dragon, Sintel decides to embark on a dangerous quest to find her lost friend Scales.',
    poster: 'https://upload.wikimedia.org/wikipedia/commons/thumb/8/8f/Sintel_poster.jpg/440px-Sintel_poster.jpg',
    backdrop: 'https://upload.wikimedia.org/wikipedia/commons/thumb/8/8f/Sintel_poster.jpg/1024px-Sintel_poster.jpg',
    streamUrl: 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/Sintel.mp4',
    streamKind: 'file',
    runtimeMinutes: 15,
    genres: ['Animation', 'Fantasy'],
  },
  {
    id: 'elephants-dream',
    type: 'movie',
    title: "Elephants Dream",
    year: 2006,
    overview:
      'Two strange characters explore a capricious and seemingly infinite machine. The elder, Proog, acts as a tour-guide and protector, while the younger Emo tries to make sense of an increasingly strange and hostile environment.',
    poster: 'https://upload.wikimedia.org/wikipedia/commons/thumb/e/e8/Elephants_Dream_s5_both.jpg/440px-Elephants_Dream_s5_both.jpg',
    backdrop: 'https://upload.wikimedia.org/wikipedia/commons/thumb/e/e8/Elephants_Dream_s5_both.jpg/1024px-Elephants_Dream_s5_both.jpg',
    streamUrl: 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ElephantsDream.mp4',
    streamKind: 'file',
    runtimeMinutes: 11,
    genres: ['Animation', 'Sci-Fi'],
  },
  {
    id: 'tears-of-steel',
    type: 'movie',
    title: 'Tears of Steel',
    year: 2012,
    overview:
      'In an apocalyptic future, a group of soldiers and scientists take refuge in Amsterdam to try to stop an army of robots that threatens the planet.',
    poster: 'https://upload.wikimedia.org/wikipedia/commons/thumb/1/13/Tears_of_Steel_poster.jpg/440px-Tears_of_Steel_poster.jpg',
    backdrop: 'https://upload.wikimedia.org/wikipedia/commons/thumb/1/13/Tears_of_Steel_poster.jpg/1024px-Tears_of_Steel_poster.jpg',
    streamUrl: 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/TearsOfSteel.mp4',
    streamKind: 'file',
    runtimeMinutes: 12,
    genres: ['Sci-Fi', 'Action'],
  },
  {
    id: 'hls-demo',
    type: 'movie',
    title: 'HLS Demo Stream',
    year: 2020,
    overview:
      'A public HLS test stream (Mux sample) for verifying adaptive playback. Not a feature film — used to exercise the player.',
    poster: 'https://images.unsplash.com/photo-1485846234645-a62644f84728?w=440&h=660&fit=crop',
    backdrop: 'https://images.unsplash.com/photo-1485846234645-a62644f84728?w=1280&h=720&fit=crop',
    streamUrl: 'https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8',
    streamKind: 'hls',
    runtimeMinutes: 10,
    genres: ['Demo', 'Tech'],
  },
]

export function getById(id: string): CatalogItem | undefined {
  return catalog.find((item) => item.id === id)
}

export function searchCatalog(query: string): CatalogItem[] {
  const q = query.trim().toLowerCase()
  if (!q) return catalog
  return catalog.filter(
    (item) =>
      item.title.toLowerCase().includes(q) ||
      item.genres.some((g) => g.toLowerCase().includes(q)) ||
      item.overview.toLowerCase().includes(q),
  )
}
