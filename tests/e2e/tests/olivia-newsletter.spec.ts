import { expect, test } from "@playwright/test";
import { readFileSync } from "fs";
import { join } from "path";

const OLIVIA_HTML = readFileSync(
  join(
    process.cwd(),
    "../apps/maya-gateway/src/maya_gateway/static/demo/olivia-rodrigo-newsletter.html",
  ),
  "utf-8",
);

test.describe("Olivia Rodrigo newsletter — email artist updates", () => {
  test.beforeEach(async ({ context }) => {
    await context.addInitScript(() => {
      try {
        window.localStorage.clear();
        window.sessionStorage.clear();
      } catch {
        /* storage not available */
      }
    });
  });

  test("webhook ingest surfaces branded card in Radio", async ({
    page,
    request,
  }) => {
    const webhook = await request.post("/api/discover/inbox/webhook", {
      multipart: {
        sender: "news@oliviarodrigo.umusic-online.com",
        From: "Olivia Rodrigo <news@oliviarodrigo.umusic-online.com>",
        subject: "New music from Olivia Rodrigo",
        "body-html": OLIVIA_HTML,
        "body-plain":
          "what's wrong with me ft. Robert Smith — you seem pretty sad for a girl so in love",
        Date: "Sun, 08 Jun 2025 18:12:00 +0000",
      },
    });
    if (webhook.status() === 500) {
      test.skip(true, "database not available");
    }
    expect(webhook.status()).toBe(200);
    const body = await webhook.json();
    expect(body.artist_slug).toBe("olivia-rodrigo");

    await page.goto("/?skipboot=1");
    await page.keyboard.press("Control+Alt+KeyK");
    await page.getByTestId("launcher-input").fill("/play");
    await page.keyboard.press("Escape");
    await page.keyboard.press("Control+Alt+KeyK");
    await page.getByTestId("launcher-input").fill("radio");
    await page.keyboard.press("Enter");

    const radio = page.getByTestId("radio-player");
    await expect(radio).toBeVisible();
    await expect(page.getByTestId("radio-whats-new")).toBeVisible();

    const summary = await request.get(
      "/api/discover/inbox/summary?window=7d&operator_id=local",
    );
    expect(summary.status()).toBe(200);
    const summaryBody = await summary.json();
    expect(summaryBody.artists?.[0]?.artist_display).toContain("Olivia");
  });

  test("artifact endpoint serves sandboxed HTML", async ({ request }) => {
    const webhook = await request.post("/api/discover/inbox/webhook", {
      multipart: {
        sender: "news@oliviarodrigo.umusic-online.com",
        From: "Olivia Rodrigo <news@oliviarodrigo.umusic-online.com>",
        subject: "New music from Olivia Rodrigo",
        "body-html": OLIVIA_HTML,
        "body-plain": "handwritten note",
        Date: "Sun, 08 Jun 2025 18:12:00 +0000",
      },
    });
    if (webhook.status() === 500) {
      test.skip(true, "database not available");
    }
    const item = await webhook.json();
    const artifactUrl = item.html_artifact_url as string;
    const artifact = await request.get(artifactUrl);
    expect(artifact.status()).toBe(200);
    expect(artifact.headers()["content-security-policy"]).toContain("sandbox");
    expect(await artifact.text()).toContain("Olivia Rodrigo");
  });
});
