import assert from "node:assert/strict"
import test from "node:test"
import { isTracklistUrl, legacyCaptureType, targetUrl } from "../src/capture-command.ts"

test("recognizes supported tracklist URLs conservatively", () => {
  assert.equal(isTracklistUrl("https://www.youtube.com/watch?v=abc"), true)
  assert.equal(isTracklistUrl("https://youtu.be/abc"), false)
  assert.equal(isTracklistUrl("https://www.1001tracklists.com/tracklist/abc/show.html"), true)
  assert.equal(isTracklistUrl("https://music.apple.com/us/album/example/123"), true)
  assert.equal(isTracklistUrl("https://example.com/article"), false)
})

test("maps normalized commands to legacy capture types", () => {
  assert.equal(legacyCaptureType({ operation: "capture.page" }, "https://example.com", "article"), "article")
  assert.equal(legacyCaptureType({ operation: "capture.screenshot" }, "https://example.com", "article"), "generic")
  assert.equal(legacyCaptureType({ operation: "capture.image" }, "https://example.com/image.png", "article"), "image")
  assert.equal(legacyCaptureType({ operation: "capture.page" }, "https://youtube.com/watch?v=abc", "article"), "tracklist")
})

test("uses explicit link and image targets", () => {
  assert.equal(targetUrl({ operation: "capture.link", linkUrl: "https://target.test" }, "https://page.test"), "https://target.test")
  assert.equal(targetUrl({ operation: "capture.image", srcUrl: "https://page.test/image.jpg" }, "https://page.test"), "https://page.test/image.jpg")
  assert.equal(targetUrl({ operation: "capture.selection" }, "https://page.test"), "https://page.test")
})
