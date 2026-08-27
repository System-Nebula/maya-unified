import { api, call } from "../api"
import { targetUrl } from "../capture-command"
import type { ArtifactKind, BrowserSession, CaptureCommand, CaptureResult, ExtractedPage } from "../protocol"

const HOST = "org.lamia.browser"
const SESSION_KEY = "lamia.browser.session"

async function httpError(label: string, response: Response): Promise<Error> {
  let message = `${label}: HTTP ${response.status}`
  try {
    const body = await response.json()
    const detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)
    message = `${label}: ${detail || `HTTP ${response.status}`}`
    if (body.trace_id) message += ` [trace_id=${body.trace_id}${body.span_id ? ` span_id=${body.span_id}` : ""}]`
  } catch { /* retain status-only message */ }
  return new Error(message)
}

async function runtimeInfo() {
  const info = await api.runtime.getPlatformInfo()
  const browser = __MAYA_FIREFOX__ ? "firefox" : navigator.userAgent.includes("Vivaldi") ? "vivaldi" : "chromium"
  return { browser, platform: info.os, extension_id: api.runtime.id, extension_version: api.runtime.getManifest().version }
}

async function nativeMessage(payload: Record<string, unknown>): Promise<Record<string, any>> {
  const response = await call<Record<string, any>>((callback) => api.runtime.sendNativeMessage(HOST, payload, callback))
  if (response.error) throw new Error(response.error)
  if (response.pending) throw new Error(`Pairing awaits confirmation at ${response.confirmation_url}`)
  return response
}

export async function lamiaSession(): Promise<BrowserSession> {
  const stored = await api.storage.local.get(SESSION_KEY)
  const current = stored[SESSION_KEY] as BrowserSession | undefined
  if (current && current.expiresAt > Date.now() + 30_000) return current
  const boot = await nativeMessage({ type: "bootstrap", ...(await runtimeInfo()), installation_id: current?.installationId })
  const next = {
    installationId: boot.installation_id,
    sessionToken: boot.session_token,
    apiBase: boot.api_base,
    expiresAt: Date.now() + Number(boot.expires_in || 900) * 1000,
  }
  await api.storage.local.set({ [SESSION_KEY]: next })
  return next
}

async function sha256(blob: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer())
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("")
}

async function screenshot(tab: chrome.tabs.Tab) {
  const dataUrl = await call<string>((callback) => api.tabs.captureVisibleTab(tab.windowId, { format: "png" }, callback))
  return { mimeType: "image/png", dataUrl }
}

async function developerArtifacts(tabId: number) {
  if (!__MAYA_DEVTOOLS__) return {}
  const target = { tabId }
  await api.debugger.attach(target, "1.3")
  try {
    const [dom, ax] = await Promise.all([
      api.debugger.sendCommand(target, "DOMSnapshot.captureSnapshot", { computedStyles: [] }),
      api.debugger.sendCommand(target, "Accessibility.getFullAXTree"),
    ])
    return {
      dom_snapshot: { mimeType: "application/json", text: JSON.stringify(dom) },
      ax_tree: { mimeType: "application/json", text: JSON.stringify(ax) },
    }
  } finally { await api.debugger.detach(target) }
}

export async function captureLamia(command: CaptureCommand, tab: chrome.tabs.Tab, page: ExtractedPage): Promise<CaptureResult> {
  if (command.operation === "capture.screenshot" || command.operation === "capture.page") page.artifacts.screenshot = await screenshot(tab)
  Object.assign(page.artifacts, await developerArtifacts(tab.id!))
  const auth = await lamiaSession()
  const offered: Array<{ kind: ArtifactKind; mime_type: string; size_bytes: number; sha256: string; blob: Blob }> = []
  for (const [kind, artifact] of Object.entries(page.artifacts)) {
    if (!artifact) continue
    const blob = artifact.dataUrl ? await (await fetch(artifact.dataUrl)).blob() : new Blob([artifact.text || ""], { type: artifact.mimeType })
    offered.push({ kind: kind as ArtifactKind, mime_type: artifact.mimeType, size_bytes: blob.size, sha256: await sha256(blob), blob })
  }
  const url = targetUrl(command, page.url)
  const body = {
    protocol_version: "1.0", request_id: crypto.randomUUID(), occurred_at: new Date().toISOString(), operation: command.operation,
    context: {
      browser: (await runtimeInfo()).browser, extension_version: api.runtime.getManifest().version,
      browser_installation_id: auth.installationId, window_id: String(tab.windowId), tab_id: String(tab.id),
      tab_navigation_id: `${tab.id}:${page.url}`, incognito: Boolean(tab.incognito), privileged_capture: __MAYA_DEVTOOLS__,
    },
    target: {
      url,
      canonical_url: command.operation === "capture.page" || command.operation === "capture.selection" ? page.canonicalUrl : url,
      title: page.title, language: page.language || null,
    },
    metadata: { ...page.metadata, containing_page_url: page.url },
    anchors: command.operation === "capture.selection" ? page.anchors : [],
    artifacts: offered.map(({ blob: _, ...offer }) => offer),
    user_intent: command.intent || null, project_ids: [],
  }
  const response = await fetch(`${auth.apiBase}/api/v1/browser/captures`, {
    method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${auth.sessionToken}` }, body: JSON.stringify(body),
  })
  if (!response.ok) throw await httpError("Capture rejected", response)
  const accepted = await response.json()
  for (const offer of offered) {
    const upload = await fetch(`${auth.apiBase}/api/v1/browser/captures/${accepted.capture_id}/artifacts/${offer.kind}`, {
      method: "PUT", headers: { "Content-Type": offer.mime_type, "X-Content-SHA256": offer.sha256, Authorization: `Bearer ${auth.sessionToken}` }, body: offer.blob,
    })
    if (!upload.ok) throw await httpError(`Artifact ${offer.kind} failed`, upload)
  }
  const completed = await fetch(`${auth.apiBase}/api/v1/browser/captures/${accepted.capture_id}/complete`, {
    method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${auth.sessionToken}` },
    body: JSON.stringify({ artifact_kinds: offered.map((offer) => offer.kind) }),
  })
  if (!completed.ok) throw await httpError("Capture completion failed", completed)
  const final = await completed.json()
  return { captureId: accepted.capture_id, status: final.status || accepted.status, duplicate: Boolean(accepted.duplicate_request) }
}
