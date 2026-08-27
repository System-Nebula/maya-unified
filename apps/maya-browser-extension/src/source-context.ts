export interface SourceContext {
  platform: "grok"
  resourceKind: "project" | "conversation"
  sourceProjectId: string | null
  sourceConversationId: string | null
  canonicalUrn: string
  projectUrn: string | null
}

const GROK_ORIGIN = "https://grok.com"
const PROJECT_PATH = /^\/project\/([^/?#]+)\/?$/
const CONVERSATION_PATH = /^\/c\/([^/?#]+)\/?$/

function parseUrl(value: string): URL | null {
  try {
    return new URL(value, GROK_ORIGIN)
  } catch {
    return null
  }
}

function isGrok(url: URL): boolean {
  return url.protocol === "https:" && url.hostname === "grok.com"
}

export function classifySourceUrl(value: string, containingProjectId: string | null = null): SourceContext | null {
  const url = parseUrl(value)
  if (!url || !isGrok(url)) return null

  const project = PROJECT_PATH.exec(url.pathname)
  if (project) {
    const sourceProjectId = decodeURIComponent(project[1])
    const projectUrn = `urn:maya:chat:grok:project:${sourceProjectId}`
    return {
      platform: "grok",
      resourceKind: "project",
      sourceProjectId,
      sourceConversationId: null,
      canonicalUrn: projectUrn,
      projectUrn,
    }
  }

  const conversation = CONVERSATION_PATH.exec(url.pathname)
  if (!conversation) return null
  const sourceConversationId = decodeURIComponent(conversation[1])
  return {
    platform: "grok",
    resourceKind: "conversation",
    sourceProjectId: containingProjectId,
    sourceConversationId,
    canonicalUrn: `urn:maya:chat:grok:conversation:${sourceConversationId}`,
    projectUrn: containingProjectId ? `urn:maya:chat:grok:project:${containingProjectId}` : null,
  }
}

export function grokConversationLinks(values: string[]): Array<{ sourceConversationId: string; url: string }> {
  const links = new Map<string, { sourceConversationId: string; url: string }>()
  for (const value of values) {
    const url = parseUrl(value)
    if (!url || !isGrok(url)) continue
    const context = classifySourceUrl(url.href)
    if (!context || context.resourceKind !== "conversation" || !context.sourceConversationId) continue
    if (!links.has(context.sourceConversationId)) {
      links.set(context.sourceConversationId, {
        sourceConversationId: context.sourceConversationId,
        url: `${GROK_ORIGIN}/c/${encodeURIComponent(context.sourceConversationId)}`,
      })
    }
  }
  return Array.from(links.values())
}
