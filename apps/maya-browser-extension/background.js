/** Background service worker — orchestrates capture and POST to Maya gateway. */

const DEFAULT_GATEWAY = "http://localhost:8090";

async function getSettings() {
  return chrome.storage.sync.get({
    gatewayUrl: DEFAULT_GATEWAY,
    captureToken: "",
    captureType: "article",
  });
}

function arrayBufferToBase64(buffer) {
  let binary = "";
  const bytes = new Uint8Array(buffer);
  for (let i = 0; i < bytes.byteLength; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

async function captureVisibleTabBase64(windowId) {
  const dataUrl = await chrome.tabs.captureVisibleTab(windowId, { format: "webp", quality: 85 });
  const resp = await fetch(dataUrl);
  const buf = await resp.arrayBuffer();
  return arrayBufferToBase64(buf);
}

async function extractFromTab(tabId) {
  return chrome.tabs.sendMessage(tabId, { type: "maya.extractPage" });
}

async function postCapture(payload, settings) {
  const url = `${settings.gatewayUrl.replace(/\/$/, "")}/api/browser/capture`;
  const headers = { "Content-Type": "application/json" };
  if (settings.captureToken) {
    headers["X-Maya-Capture-Token"] = settings.captureToken;
  }
  const resp = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
    credentials: "include",
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`capture failed (${resp.status}): ${text}`);
  }
  return resp.json();
}

async function runCapture(tab, captureTypeOverride) {
  const settings = await getSettings();
  const page = await extractFromTab(tab.id);
  const screenshotB64 = await captureVisibleTabBase64(tab.windowId);

  const assets = [
    {
      kind: "html",
      mime_type: "text/html",
      data_b64: btoa(unescape(encodeURIComponent(page.html.slice(0, 500000)))),
    },
    {
      kind: "screenshot",
      mime_type: "image/webp",
      data_b64: screenshotB64,
    },
  ];

  if (page.reader_text) {
    assets.push({
      kind: "reader_html",
      mime_type: "text/plain",
      data_b64: btoa(unescape(encodeURIComponent(page.reader_text.slice(0, 100000)))),
    });
  }

  const payload = {
    event: "browser.capture",
    capture_type: captureTypeOverride || settings.captureType || "article",
    url: page.url || tab.url,
    title: page.title || tab.title,
    selection: page.selection || "",
    reader_text: page.reader_text || "",
    favicon_url: page.favicon_url,
    tags: [],
    metadata: page.metadata || {},
    assets,
    client_captured_at: Date.now() / 1000,
  };

  const manifest = await postCapture(payload, settings);
  return manifest;
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "maya-save",
    title: "Save to Maya",
    contexts: ["page", "selection", "link", "image"],
  });
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "maya-save" || !tab?.id) {
    return;
  }
  try {
    const manifest = await runCapture(tab);
    console.info("Maya capture ok", manifest);
  } catch (err) {
    console.error("Maya capture failed", err);
  }
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "maya.captureActiveTab") {
    chrome.tabs.query({ active: true, currentWindow: true }, async (tabs) => {
      const tab = tabs[0];
      if (!tab?.id) {
        sendResponse({ ok: false, error: "no active tab" });
        return;
      }
      try {
        const manifest = await runCapture(tab, msg.captureType);
        sendResponse({ ok: true, manifest });
      } catch (err) {
        sendResponse({ ok: false, error: String(err.message || err) });
      }
    });
    return true;
  }
  return false;
});
