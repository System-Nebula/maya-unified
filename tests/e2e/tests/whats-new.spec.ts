import { expect, test } from "@playwright/test";

test.describe("What's New — unified discover feed", () => {
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

  test("opens via launcher /new and renders feed shell", async ({ page }) => {
    await page.goto("/?skipboot=1");

    const launcherInput = page.getByTestId("launcher-input");
    await page.keyboard.press("Control+Alt+KeyK");
    await expect(launcherInput).toBeVisible();
    await launcherInput.fill("/new this week");
    await page.keyboard.press("Enter");

    const app = page.getByTestId("whats-new-app");
    await expect(app).toBeVisible();
    await expect(page.getByTestId("inbox-strip")).toBeVisible();
    await expect(page.getByTestId("genre-pills")).toBeVisible();
    await expect(page.getByTestId("source-toggles")).toBeVisible();
    await expect(page.getByTestId("feed-card-list")).toBeVisible();
    await expect(page.getByTestId("artist-tracker")).toBeVisible();
  });

  test("genre pill toggle triggers preference patch and feed refresh", async ({
    page,
  }) => {
    await page.goto("/?skipboot=1");
    await page.keyboard.press("Control+Alt+KeyK");
    await page.getByTestId("launcher-input").fill("/new");
    await page.keyboard.press("Enter");

    const techno = page.getByTestId("genre-pill-techno");
    await expect(techno).toBeVisible();

    const patchPromise = page.waitForRequest(
      (req) =>
        req.url().includes("/api/discover/preferences") &&
        req.method() === "PATCH",
    );
    await techno.click();
    const patchReq = await patchPromise;
    expect(patchReq.postDataJSON()).toMatchObject({
      genre_weights: { techno: 1 },
    });

    await expect(techno).toHaveAttribute("data-active", "true");
  });

  test("discover feed API returns ranked items envelope", async ({
    request,
  }) => {
    const res = await request.get(
      "/api/discover/feed?window=7d&limit=5&operator_id=local",
    );
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty("items");
    expect(body).toHaveProperty("window", "7d");
    expect(Array.isArray(body.items)).toBe(true);
  });

  test("ask endpoint parses this week skrillex", async ({ request }) => {
    const res = await request.get(
      "/api/discover/feed/ask?q=" +
        encodeURIComponent("what's new this week skrillex") +
        "&operator_id=local",
    );
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.window).toBe("7d");
  });
});
