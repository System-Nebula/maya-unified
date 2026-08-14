/** Client-side prepareStream rules (P-Stream userscript protocol). */

export type StreamRule = {
  ruleId: string
  targetDomains?: string[]
  targetRegex?: string
  requestHeaders?: Record<string, string>
  responseHeaders?: Record<string, string>
}

const RULES = new Map<string, StreamRule>()

const MODIFIABLE_RESPONSE_HEADERS = new Set([
  'access-control-allow-origin',
  'access-control-allow-methods',
  'access-control-allow-headers',
  'content-security-policy',
  'content-security-policy-report-only',
  'content-disposition',
])

export function setStreamRule(rule: StreamRule) {
  const responseHeaders = Object.entries(rule.responseHeaders ?? {}).reduce(
    (acc, [k, v]) => {
      const key = k.toLowerCase()
      if (MODIFIABLE_RESPONSE_HEADERS.has(key)) acc[key] = v
      return acc
    },
    {} as Record<string, string>,
  )
  RULES.set(rule.ruleId, { ...rule, responseHeaders })
}

export function clearStreamRules() {
  RULES.clear()
}

export function findStreamRule(url: string): StreamRule | null {
  let normalized: string
  let host: string
  try {
    const parsed = new URL(url, typeof window !== 'undefined' ? window.location.href : 'http://localhost')
    normalized = parsed.toString()
    host = parsed.hostname.toLowerCase()
  } catch {
    return null
  }

  for (const rule of RULES.values()) {
    if (
      rule.targetDomains?.some((d) => {
        const domain = d.toLowerCase()
        return host === domain || host.endsWith(`.${domain}`)
      })
    ) {
      return rule
    }
    if (rule.targetRegex) {
      try {
        if (new RegExp(rule.targetRegex).test(normalized)) return rule
      } catch {
        /* ignore bad regex */
      }
    }
  }
  return null
}

export function headersForStreamUrl(url: string): Record<string, string> {
  const rule = findStreamRule(url)
  return { ...(rule?.requestHeaders || {}) }
}
