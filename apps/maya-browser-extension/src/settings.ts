import { api } from "./api"
import { normalizeSettings } from "./settings-normalize"
import type { Settings } from "./settings-normalize"

export type { Settings } from "./settings-normalize"
export { DEFAULT_SETTINGS } from "./settings-normalize"

export async function getSettings(): Promise<Settings> {
  const [raw, local] = await Promise.all([
    api.storage.sync.get(null),
    api.storage.local.get("lamia.browser.session"),
  ])
  return normalizeSettings(raw, Boolean(local["lamia.browser.session"]))
}

export async function saveSettings(settings: Settings): Promise<void> {
  await api.storage.sync.set(settings)
}
