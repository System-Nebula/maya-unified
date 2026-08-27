import { api, call } from "../api"
import { legacyCaptureType, targetUrl } from "../capture-command"
import type { CaptureCommand, CaptureResult, ExtractedPage } from "../protocol"
import type { Settings } from "../settings"

function textToBase64(text: string): string {
  const bytes = new TextEncoder().encode(text)
  let binary = ""
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000))
  }
  return btoa(binary)
}

async function visibleScreenshot(tab: chrome.tabs.Tab): Promise<string> {
  const dataUrl = await call<string>((callback) => api.tabs.captureVisibleTab(tab.windowId, { format: "jpeg", quality: 85 }, callback))
  const bytes = new Uint8Array(await (await fetch(dataUrl)).arrayBuffer())
  let binary = ""
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000))
  }
  return btoa(binary)
}

export async function captureLegacy(
  command: CaptureCommand, tab: chrome.tabs.Tab, page: ExtractedPage, settings: Settings,
): Promise<CaptureResult> {
  const url = targetUrl(command, page.url)
  const html = page.artifacts.page_html?.text || ""
  const reader = page.artifacts.reader_text?.text || ""
  const assets = [
    { kind: "html", mime_type: "text/html", data_b64: textToBase64(html.slice(0, 500_000)) },
    { kind: "screenshot", mime_type: "image/jpeg", data_b64: await visibleScreenshot(tab) },
  ]
  if (reader) assets.push({ kind: "reader_html", mime_type: "text/plain", data_b64: textToBase64(reader.slice(0, 100_000)) })
  const metadata = { ...page.metadata, canonical: page.canonicalUrl, user_intent: command.intent || undefined, containing_page_url: page.url }
  const response = await fetch(`${settings.gatewayUrl.replace(/\/$/, "")}/api/browser/capture`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(settings.captureToken ? { "X-Maya-Capture-Token": settings.captureToken } : {}),
    },
    credentials: "include",
    body: JSON.stringify({
      event: "browser.capture",
      capture_type: legacyCaptureType(command, url, settings.defaultCaptureType),
      url,
      title: page.title || tab.title,
      selection: page.selection,
      reader_text: reader.slice(0, 100_000),
      favicon_url: page.faviconUrl,
      tags: [], metadata, assets,
      client_captured_at: Date.now() / 1000,
    }),
  })
  if (!response.ok) throw new Error(`Legacy capture failed (${response.status}): ${await response.text()}`)
  const result = await response.json()
  return { captureId: result.capture_id, status: result.duplicate ? "duplicate" : "queued", duplicate: Boolean(result.duplicate) }
}
