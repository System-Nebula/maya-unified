import assert from "node:assert/strict"
import { readFile } from "node:fs/promises"
import path from "node:path"
import test from "node:test"

const root = path.resolve(import.meta.dirname, "..")
async function manifest(target) {
  return JSON.parse(await readFile(path.join(root, "dist", target, "manifest.json"), "utf8"))
}

test("all targets are Maya builds with options and explicit native messaging", async () => {
  for (const target of ["chromium", "firefox", "chromium-devtools"]) {
    const value = await manifest(target)
    assert.match(value.name, /^Maya Browser Companion/)
    assert.equal(value.options_ui.page, "options.html")
    assert.ok(value.permissions.includes("nativeMessaging"))
    assert.deepEqual(value.host_permissions, ["<all_urls>"])
  }
})

test("debugger permission is isolated to the privileged Chromium target", async () => {
  assert.equal((await manifest("chromium-devtools")).permissions.includes("debugger"), true)
  assert.equal((await manifest("chromium")).permissions.includes("debugger"), false)
  assert.equal((await manifest("firefox")).permissions.includes("debugger"), false)
})

test("browser-specific panels and stable identities are retained", async () => {
  const chromium = await manifest("chromium")
  const firefox = await manifest("firefox")
  assert.equal(chromium.side_panel.default_path, "sidepanel.html")
  assert.ok(chromium.key)
  assert.equal(firefox.sidebar_action.default_panel, "sidebar.html")
  assert.equal(firefox.browser_specific_settings.gecko.id, "browser-adapter@lamia.local")
})
