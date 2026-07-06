/** Extract page context from the active tab DOM. */

function extractReaderText() {
  const article = document.querySelector("article");
  if (article) {
    return article.innerText.slice(0, 50000);
  }
  const main = document.querySelector("main");
  if (main) {
    return main.innerText.slice(0, 50000);
  }
  return document.body?.innerText?.slice(0, 50000) || "";
}

function extractMetadata() {
  const meta = {};
  document.querySelectorAll("meta[name], meta[property]").forEach((el) => {
    const key = el.getAttribute("name") || el.getAttribute("property");
    const content = el.getAttribute("content");
    if (key && content) {
      meta[key] = content;
    }
  });
  meta.canonical = document.querySelector('link[rel="canonical"]')?.href || location.href;
  return meta;
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type !== "maya.extractPage") {
    return false;
  }
  const selection = window.getSelection()?.toString()?.slice(0, 8000) || "";
  const html = document.documentElement.outerHTML.slice(0, 500000);
  sendResponse({
    url: location.href,
    title: document.title,
    selection,
    reader_text: extractReaderText(),
    metadata: extractMetadata(),
    html,
    favicon_url: document.querySelector('link[rel="icon"]')?.href || null,
  });
  return true;
});
