/**
 * In-app P-Stream userscript protocol — no Tampermonkey.
 * Speaks hello / makeRequest / prepareStream / openPage via postMessage,
 * fulfilled by the lab `/api/fetch` + stream rule store.
 */
import { clearStreamRules, setStreamRule } from './streamRules'

const SCRIPT_VERSION = '1.4.0-cinemaya'

type RelayMessage = {
  name?: string
  relayId?: string | number
  instanceId?: string | number
  body?: unknown
  relayed?: boolean
  __internal?: boolean
}

function reply(
  source: MessageEventSource | null,
  origin: string,
  payload: Record<string, unknown>,
) {
  try {
    source?.postMessage(payload, { targetOrigin: origin === 'null' ? '*' : origin })
  } catch {
    try {
      ;(source as Window)?.postMessage(payload, origin === 'null' ? '*' : origin)
    } catch {
      /* ignore */
    }
  }
}

async function handleMakeRequest(reqBody: {
  url?: string
  baseUrl?: string
  query?: Record<string, string>
  method?: string
  headers?: Record<string, string>
  body?: unknown
  bodyType?: string
  credentials?: string
  withCredentials?: boolean
}) {
  if (!reqBody?.url && !reqBody?.baseUrl) {
    throw new Error('No request body found in the request.')
  }

  const res = await fetch('/api/fetch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      url: reqBody.url,
      baseUrl: reqBody.baseUrl,
      query: reqBody.query,
      method: reqBody.method || 'GET',
      headers: reqBody.headers,
      body: reqBody.body,
    }),
  })

  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error((data as { error?: string }).error || `Fetch failed (${res.status})`)
  }
  if ((data as { success?: boolean }).success === false) {
    throw new Error((data as { error?: string }).error || 'Fetch failed')
  }
  return {
    success: true,
    response: (data as { response: unknown }).response,
  }
}

function handlePrepareStream(reqBody: {
  ruleId?: string
  targetDomains?: string[]
  targetRegex?: string
  requestHeaders?: Record<string, string>
  responseHeaders?: Record<string, string>
}) {
  if (!reqBody?.ruleId) throw new Error('No request body found in the request.')
  setStreamRule({
    ruleId: String(reqBody.ruleId),
    targetDomains: reqBody.targetDomains,
    targetRegex: reqBody.targetRegex,
    requestHeaders: reqBody.requestHeaders,
    responseHeaders: reqBody.responseHeaders,
  })
  return { success: true }
}

function handleOpenPage(reqBody: { redirectUrl?: string }) {
  if (reqBody?.redirectUrl) window.location.href = reqBody.redirectUrl
  return { success: true }
}

async function dispatch(name: string, body: unknown) {
  switch (name) {
    case 'hello':
      return {
        success: true,
        version: SCRIPT_VERSION,
        allowed: true,
        hasPermission: true,
      }
    case 'makeRequest':
      return handleMakeRequest((body || {}) as Parameters<typeof handleMakeRequest>[0])
    case 'prepareStream':
      return handlePrepareStream((body || {}) as Parameters<typeof handlePrepareStream>[0])
    case 'openPage':
      return handleOpenPage((body || {}) as Parameters<typeof handleOpenPage>[0])
    default:
      return null
  }
}

let installed = false

/** Install once — safe to call from React layout. Returns disposer. */
export function installPstreamBridge() {
  if (installed || typeof window === 'undefined') {
    return () => {}
  }
  installed = true

  const onMessage = async (event: MessageEvent<RelayMessage>) => {
    const data = event.data
    if (!data || data.__internal || data.relayed) return
    const name = data.name
    if (
      name !== 'hello' &&
      name !== 'makeRequest' &&
      name !== 'prepareStream' &&
      name !== 'openPage'
    ) {
      return
    }

    try {
      const result = await dispatch(name, data.body)
      if (result == null) return
      reply(event.source, event.origin || '/', {
        name,
        relayId: data.relayId,
        instanceId: data.instanceId,
        body: result,
        relayed: true,
      })
    } catch (err) {
      reply(event.source, event.origin || '/', {
        name,
        relayId: data.relayId,
        instanceId: data.instanceId,
        body: {
          success: false,
          error: err instanceof Error ? err.message : String(err),
        },
        relayed: true,
      })
    }
  }

  window.addEventListener('message', onMessage)
  if (import.meta.env.DEV) {
    console.debug('[pstream-bridge] installed', SCRIPT_VERSION)
  }

  return () => {
    window.removeEventListener('message', onMessage)
    clearStreamRules()
    installed = false
  }
}
