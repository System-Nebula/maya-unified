import { getSettings, saveSettings } from "./settings"
import type { Destination, LegacyCaptureType } from "./protocol"

const form = document.querySelector<HTMLFormElement>("#settings")!
const destination = document.querySelector<HTMLSelectElement>("#destination")!
const gatewayUrl = document.querySelector<HTMLInputElement>("#gatewayUrl")!
const captureToken = document.querySelector<HTMLInputElement>("#captureToken")!
const defaultCaptureType = document.querySelector<HTMLSelectElement>("#defaultCaptureType")!
const legacyFields = document.querySelector<HTMLElement>("#legacyFields")!
const saved = document.querySelector<HTMLElement>("#saved")!

function showDestinationFields() {
  legacyFields.hidden = destination.value !== "legacy"
}

document.addEventListener("DOMContentLoaded", async () => {
  const settings = await getSettings()
  destination.value = settings.destination
  gatewayUrl.value = settings.gatewayUrl
  captureToken.value = settings.captureToken
  defaultCaptureType.value = settings.defaultCaptureType
  showDestinationFields()
})
destination.addEventListener("change", showDestinationFields)
form.addEventListener("submit", async (event) => {
  event.preventDefault()
  await saveSettings({
    destination: destination.value as Destination,
    gatewayUrl: gatewayUrl.value.trim(),
    captureToken: captureToken.value.trim(),
    defaultCaptureType: defaultCaptureType.value as LegacyCaptureType,
  })
  saved.textContent = "Saved. New captures will use this destination."
})
