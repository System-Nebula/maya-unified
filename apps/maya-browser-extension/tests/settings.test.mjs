import assert from "node:assert/strict"
import test from "node:test"

const { normalizeSettings } = await import("../src/settings-normalize.ts")

test("fresh installs default to the legacy destination", () => {
  assert.deepEqual(normalizeSettings({}), {
    destination: "legacy",
    gatewayUrl: "http://localhost:8090",
    captureToken: "",
    defaultCaptureType: "article",
  })
})

test("existing Lamia sessions retain the Lamia destination", () => {
  assert.equal(normalizeSettings({}, true).destination, "lamia")
  assert.equal(normalizeSettings({ destination: "legacy" }, true).destination, "legacy")
})

test("legacy settings migrate the old captureType key", () => {
  const settings = normalizeSettings({ gatewayUrl: "http://gateway.test", captureToken: "secret", captureType: "paper" })
  assert.equal(settings.gatewayUrl, "http://gateway.test")
  assert.equal(settings.captureToken, "secret")
  assert.equal(settings.defaultCaptureType, "paper")
})
