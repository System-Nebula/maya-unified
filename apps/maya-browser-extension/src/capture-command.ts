import type { CaptureCommand, LegacyCaptureType } from "./protocol"

export function isTracklistUrl(url: string): boolean {
  try {
    const parsed = new URL(url)
    const host = parsed.hostname.replace(/^www\./, "")
    if (host === "youtu.be" || host.includes("youtube.com")) return Boolean(parsed.searchParams.get("v"))
    if (host.includes("1001tracklists.com")) return /\/tracklist\/[a-z0-9]+/i.test(parsed.pathname)
    if (host.includes("music.apple.com")) return /\/album\//i.test(parsed.pathname)
  } catch { return false }
  return false
}

export function targetUrl(command: CaptureCommand, pageUrl: string): string {
  if (command.operation === "capture.link") return command.linkUrl || pageUrl
  if (command.operation === "capture.image") return command.srcUrl || pageUrl
  return pageUrl
}

export function legacyCaptureType(command: CaptureCommand, url: string, configured: LegacyCaptureType): LegacyCaptureType {
  if (command.operation === "capture.screenshot") return "generic"
  if (command.operation === "capture.image") return "image"
  if (isTracklistUrl(url)) return "tracklist"
  return configured
}
