import { api, call } from "./api"
import type { CaptureCommand, CaptureResult, ExtractedPage } from "./protocol"
import { getSettings } from "./settings"
import { captureLegacy } from "./transports/legacy"
import { captureLamia, lamiaSession } from "./transports/lamia"

async function activeTab(): Promise<chrome.tabs.Tab> {
  const tabs = await call<chrome.tabs.Tab[]>((callback) => api.tabs.query({ active: true, currentWindow: true }, callback))
  const tab = tabs[0]
  if (!tab?.id || !tab.url) throw new Error("No capturable active tab")
  return tab
}

async function capture(command: CaptureCommand, suppliedTab?: chrome.tabs.Tab): Promise<CaptureResult> {
  const tab = suppliedTab?.id && suppliedTab.url ? suppliedTab : await activeTab()
  const page = await call<ExtractedPage>((callback) => api.tabs.sendMessage(tab.id!, { type: "maya.extract" }, callback))
  const settings = await getSettings()
  return settings.destination === "lamia"
    ? captureLamia(command, tab, page)
    : captureLegacy(command, tab, page, settings)
}

function registerMenus() {
  api.contextMenus.removeAll(() => {
    api.contextMenus.create({ id: "maya-page", title: "Save page to Maya", contexts: ["page"] })
    api.contextMenus.create({ id: "maya-selection", title: "Save selection to Maya", contexts: ["selection"] })
    api.contextMenus.create({ id: "maya-link", title: "Save link to Maya", contexts: ["link"] })
    api.contextMenus.create({ id: "maya-image", title: "Save image to Maya", contexts: ["image"] })
  })
}

api.runtime.onInstalled.addListener(registerMenus)
api.contextMenus.onClicked.addListener((info, tab) => {
  const operation = info.menuItemId === "maya-selection" ? "capture.selection"
    : info.menuItemId === "maya-link" ? "capture.link"
    : info.menuItemId === "maya-image" ? "capture.image" : "capture.page"
  void capture({ operation, linkUrl: info.linkUrl, srcUrl: info.srcUrl }, tab).catch(console.error)
})
api.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "maya.capture") {
    capture(message.command).then((result) => sendResponse({ ok: true, result })).catch((error) => sendResponse({ ok: false, error: String(error.message || error) }))
    return true
  }
  if (message?.type === "maya.status") {
    getSettings().then(async (settings) => {
      if (settings.destination === "legacy") return sendResponse({ ok: true, destination: "legacy", label: "Legacy gateway" })
      try {
        await lamiaSession()
        sendResponse({ ok: true, destination: "lamia", label: "Lamia v1 paired" })
      } catch (error) { sendResponse({ ok: false, destination: "lamia", label: "Lamia v1", error: String(error) }) }
    })
    return true
  }
  return false
})

if (!__MAYA_FIREFOX__ && api.sidePanel) void api.sidePanel.setPanelBehavior({ openPanelOnActionClick: true })
