import assert from "node:assert/strict"
import test from "node:test"

import { classifySourceUrl, grokConversationLinks } from "../src/source-context.ts"

const PROJECT_ID = "ee313877-a631-4c08-b2c8-5935ff5a757d"

test("classifies a Grok project with a stable Maya namespace", () => {
  assert.deepEqual(
    classifySourceUrl(`https://grok.com/project/${PROJECT_ID}?tab=conversations`),
    {
      platform: "grok",
      resourceKind: "project",
      sourceProjectId: PROJECT_ID,
      sourceConversationId: null,
      canonicalUrn: `urn:maya:chat:grok:project:${PROJECT_ID}`,
      projectUrn: `urn:maya:chat:grok:project:${PROJECT_ID}`,
    },
  )
})

test("classifies a Grok conversation and preserves project context when supplied", () => {
  assert.deepEqual(
    classifySourceUrl("https://grok.com/c/conversation-123", PROJECT_ID),
    {
      platform: "grok",
      resourceKind: "conversation",
      sourceProjectId: PROJECT_ID,
      sourceConversationId: "conversation-123",
      canonicalUrn: "urn:maya:chat:grok:conversation:conversation-123",
      projectUrn: `urn:maya:chat:grok:project:${PROJECT_ID}`,
    },
  )
})

test("does not invent source identity for unrelated pages", () => {
  assert.equal(classifySourceUrl("https://example.com/project/123"), null)
})

test("extracts and deduplicates Grok conversation links", () => {
  assert.deepEqual(
    grokConversationLinks([
      "https://grok.com/c/one",
      "https://grok.com/c/one?ref=project",
      "/c/two",
      "https://example.com/c/nope",
      "not a url",
    ]),
    [
      { sourceConversationId: "one", url: "https://grok.com/c/one" },
      { sourceConversationId: "two", url: "https://grok.com/c/two" },
    ],
  )
})
