import { api } from "./api"
import type { CaptureOperation } from "./protocol"

const status = document.querySelector<HTMLElement>("#status")!
const destination = document.querySelector<HTMLElement>("#destination")!
const intent = document.querySelector<HTMLInputElement>("#intent")!

async function capture(operation: CaptureOperation) {
  status.textContent = "Capturing…"
  const response = await api.runtime.sendMessage({ type: "maya.capture", command: { operation, intent: intent.value.trim() } })
  if (!response?.ok) {
    status.textContent = response?.error || "Capture failed"
    return
  }
  const result = response.result
  status.textContent = result.duplicate ? `Already saved — ${result.captureId}` : `${result.status} — ${result.captureId}`
}

document.querySelector("#page")?.addEventListener("click", () => capture("capture.page"))
document.querySelector("#selection")?.addEventListener("click", () => capture("capture.selection"))
document.querySelector("#screenshot")?.addEventListener("click", () => capture("capture.screenshot"))
document.querySelector("#options")?.addEventListener("click", () => api.runtime.openOptionsPage())

void api.runtime.sendMessage({ type: "maya.status" }).then((response) => {
  destination.textContent = response?.label || "Unknown destination"
  status.textContent = response?.ok ? "Ready." : response?.error || "Destination unavailable"
})
