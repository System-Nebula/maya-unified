import { api } from "./api"
import { classifySourceUrl, grokConversationLinks } from "./source-context"

function semanticDOM() {
  const selector = "h1,h2,h3,h4,h5,h6,a,button,input,select,textarea,[role],[aria-label],main,article,nav"
  return Array.from(document.querySelectorAll(selector)).slice(0, 5000).map((node, index) => {
    const el = node as HTMLElement
    return {
      index, tag: el.tagName.toLowerCase(), role: el.getAttribute("role"),
      name: el.getAttribute("aria-label") || el.getAttribute("title") || el.innerText?.trim().slice(0, 500) || null,
      state: {
        disabled: el.getAttribute("aria-disabled") ?? (el as HTMLInputElement).disabled ?? false,
        expanded: el.getAttribute("aria-expanded"),
        checked: el.getAttribute("aria-checked") ?? (el as HTMLInputElement).checked ?? null,
      },
      href: el instanceof HTMLAnchorElement ? el.href : null,
    }
  })
}

function selectionAnchor() {
  const selection = window.getSelection()
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return []
  const quote = selection.toString().slice(0, 16000)
  const text = document.body?.innerText || ""
  const at = text.indexOf(quote)
  const range = selection.getRangeAt(0)
  const node = range.startContainer.parentElement
  return [{
    quote,
    prefix: at >= 0 ? text.slice(Math.max(0, at - 64), at) : "",
    suffix: at >= 0 ? text.slice(at + quote.length, at + quote.length + 64) : "",
    text_fragment: `:~:text=${encodeURIComponent(quote.slice(0, 500))}`,
    dom_path: node ? `${node.tagName.toLowerCase()}${node.id ? `#${CSS.escape(node.id)}` : ""}` : null,
    start_offset: range.startOffset,
    end_offset: range.endOffset,
  }]
}

function extract() {
  const metadata: Record<string, string> = {}
  document.querySelectorAll("meta[name],meta[property]").forEach((node) => {
    const key = node.getAttribute("name") || node.getAttribute("property")
    const value = node.getAttribute("content")
    if (key && value) metadata[key] = value
  })
  const jsonLd = Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map((node) => node.textContent || "")
  const links = Array.from(document.links).slice(0, 5000).map((link) => ({ href: link.href, text: link.innerText.slice(0, 500) }))
  const sourceContext = classifySourceUrl(location.href)
  const projectConversations = sourceContext?.resourceKind === "project"
    ? grokConversationLinks(links.map((link) => link.href))
    : []
  if (sourceContext) {
    metadata["maya:source_context"] = JSON.stringify(sourceContext)
    metadata["maya:canonical_urn"] = sourceContext.canonicalUrn
    if (sourceContext.projectUrn) metadata["maya:project_urn"] = sourceContext.projectUrn
  }
  if (projectConversations.length) {
    metadata["maya:project_conversations"] = JSON.stringify(projectConversations)
    metadata["maya:project_conversation_count"] = String(projectConversations.length)
  }
  const reader = document.querySelector("article,main")?.textContent || document.body?.innerText || ""
  return {
    url: location.href,
    canonicalUrl: (document.querySelector('link[rel="canonical"]') as HTMLLinkElement | null)?.href || location.href,
    title: document.title,
    language: document.documentElement.lang || "",
    selection: window.getSelection()?.toString().slice(0, 16000) || "",
    faviconUrl: (document.querySelector('link[rel="icon"]') as HTMLLinkElement | null)?.href || null,
    anchors: selectionAnchor(),
    metadata,
    artifacts: {
      page_html: { mimeType: "text/html", text: document.documentElement.outerHTML },
      reader_text: { mimeType: "text/plain", text: reader },
      semantic_dom: { mimeType: "application/json", text: JSON.stringify(semanticDOM()) },
      json_ld: { mimeType: "application/json", text: JSON.stringify(jsonLd) },
      outbound_links: { mimeType: "application/json", text: JSON.stringify(links) },
    },
  }
}

api.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "maya.extract") return false
  sendResponse(extract())
  return true
})
