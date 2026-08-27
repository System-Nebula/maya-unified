import type { Destination, LegacyCaptureType } from "./protocol"

export interface Settings {
  destination: Destination
  gatewayUrl: string
  captureToken: string
  defaultCaptureType: LegacyCaptureType
}

export const DEFAULT_SETTINGS: Settings = {
  destination: "legacy",
  gatewayUrl: "http://localhost:8090",
  captureToken: "",
  defaultCaptureType: "article",
}

export function normalizeSettings(raw: Record<string, unknown>, hasLamiaSession = false): Settings {
  const destination = raw.destination === "legacy" || raw.destination === "lamia"
    ? raw.destination
    : hasLamiaSession ? "lamia" : DEFAULT_SETTINGS.destination
  return {
    destination,
    gatewayUrl: typeof raw.gatewayUrl === "string" ? raw.gatewayUrl : DEFAULT_SETTINGS.gatewayUrl,
    captureToken: typeof raw.captureToken === "string" ? raw.captureToken : DEFAULT_SETTINGS.captureToken,
    defaultCaptureType: (typeof raw.defaultCaptureType === "string"
      ? raw.defaultCaptureType
      : typeof raw.captureType === "string" ? raw.captureType : DEFAULT_SETTINGS.defaultCaptureType) as LegacyCaptureType,
  }
}
