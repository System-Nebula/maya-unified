export type Destination = "legacy" | "lamia"
export type CaptureOperation = "capture.page" | "capture.selection" | "capture.link" | "capture.image" | "capture.screenshot"
export type ArtifactKind = "page_html" | "reader_text" | "semantic_dom" | "dom_snapshot" | "ax_tree" | "screenshot" | "json_ld" | "outbound_links"
export type LegacyCaptureType = "article" | "image" | "video" | "product" | "repo" | "paper" | "tweet" | "recipe" | "tracklist" | "generic"

export interface CaptureCommand {
  operation: CaptureOperation
  intent?: string
  linkUrl?: string
  srcUrl?: string
}

export interface ExtractedPage {
  url: string
  canonicalUrl: string
  title: string
  language: string
  selection: string
  faviconUrl: string | null
  anchors: Array<Record<string, unknown>>
  metadata: Record<string, unknown>
  artifacts: Partial<Record<ArtifactKind, { mimeType: string; text?: string; dataUrl?: string }>>
}

export interface BrowserSession {
  installationId: string
  sessionToken: string
  apiBase: string
  expiresAt: number
}

export interface CaptureResult {
  captureId: string
  status: string
  duplicate: boolean
}
