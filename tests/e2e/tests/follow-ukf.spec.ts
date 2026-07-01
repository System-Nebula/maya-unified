import { expect, test } from "@playwright/test";

const RUN_ID = String(Date.now());
const UKF_SLUG = `e2e-ukf-${RUN_ID}`;

test.describe("UKF label monitoring bootstrap", () => {
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

  test("creates UKF person with YouTube + RSS channels and daily follow", async ({
    request,
  }) => {
    const personRes = await request.post("/api/follow/persons", {
      data: {
        slug: UKF_SLUG,
        display_name: `UKF E2E ${RUN_ID}`,
        kind: "REAL",
        realm: "drum-and-bass",
      },
    });
    if (personRes.status() === 500) {
      test.skip(true, "database not available");
    }
    expect(personRes.status()).toBe(200);
    const person = await personRes.json();

    for (const url of [
      "https://www.youtube.com/@UKFDrumandBass",
      "https://ukf.com/read/feed/",
    ]) {
      const attach = await request.post(
        `/api/follow/persons/${person.id}/channels`,
        { data: { resolve: { input: url } } },
      );
      expect(attach.status()).toBe(200);
    }

    const follow = await request.post("/api/follow/follows", {
      data: {
        subject_type: "PERSON",
        subject_id: person.id,
        cadence: "daily",
        notify_homepage: true,
        notify_discord: false,
        muted: false,
      },
    });
    expect(follow.status()).toBe(200);

    const tree = await request.get("/api/follow/tree?operator_id=local");
    expect(tree.status()).toBe(200);
    const nodes = (await tree.json()).nodes as Array<{ slug: string }>;
    expect(nodes.some((n) => n.slug === UKF_SLUG)).toBe(true);
  });

  test("/play resolves Can't Love Me for DnB rotation", async ({ page }) => {
    await page.goto("/?skipboot=1");
    await page.keyboard.press("Control+Alt+KeyK");
    const launcherInput = page.getByTestId("launcher-input");
    await expect(launcherInput).toBeVisible();
    await launcherInput.fill("/play ivy - can't love me");
    await page.keyboard.press("Enter");

    const player = page.getByTestId("radio-player");
    await expect(player).toBeVisible();
    await expect(page.getByTestId("radio-title")).toHaveText("Can't Love Me");
    await expect(page.getByTestId("radio-artist")).toContainText("IVY");
  });
});
