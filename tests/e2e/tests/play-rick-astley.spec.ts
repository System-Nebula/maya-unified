import { expect, test } from "@playwright/test";

const PLAY_QUERY = "Rick Astley - Never Gonna Give You Up";

test.describe("/play Rick Astley — Never Gonna Give You Up", () => {
  test.beforeEach(async ({ context }) => {
    // The Homepage persists workspace + locked state via zustand/localStorage.
    // Wipe it before each test so we always boot into an unlocked desktop.
    await context.addInitScript(() => {
      try {
        window.localStorage.clear();
        window.sessionStorage.clear();
      } catch {
        /* storage not available */
      }
    });
  });

  test("resolves via launcher and spawns the Radio mini-player", async ({ page }) => {
    // 1. Boot into the SPA, skipping the BootScreen animation.
    await page.goto("/?skipboot=1");

    // 2. Open the launcher with the Ctrl+Alt+K shortcut (Super → Ctrl+Alt).
    const launcherInput = page.getByTestId("launcher-input");
    await page.keyboard.press("Control+Alt+KeyK");
    await expect(launcherInput).toBeVisible();
    await launcherInput.focus();

    // 3. Type the /play command and select the play result.
    await launcherInput.fill(`/play ${PLAY_QUERY}`);
    await expect(
      page.getByText(`Play: ${PLAY_QUERY}`, { exact: false }),
    ).toBeVisible();
    await page.keyboard.press("Enter");

    // 4. The Launcher closes and the RadioPlayer window opens.
    await expect(launcherInput).toBeHidden();

    const player = page.getByTestId("radio-player");
    await expect(player).toBeVisible();

    // 5. The resolver should have returned the Rick Astley demo track.
    await expect(page.getByTestId("radio-title")).toHaveText(
      "Never Gonna Give You Up",
    );
    await expect(page.getByTestId("radio-artist")).toContainText("Rick Astley");

    // 6. Match metadata: the state attribute flips to "ready" once the
    //    resolver finishes, and the player advertises how it matched.
    await expect(player).toHaveAttribute("data-state", "ready");
    await expect(player).toContainText(/matched via\s+(exact|fuzzy|demo_catalog)/i);

    // 7. The Rick Astley track ships a YouTube embed — the official channel
    //    has embedding disabled, so the player should fall back to a
    //    "Watch on YouTube" CTA pointing at the canonical watch URL.
    await expect(player).toHaveAttribute("data-source", "youtube");
    const embedHost = page.getByTestId("radio-embed");
    await expect(embedHost).toBeVisible();
    // Either the iframe loads (`youtube-embed`) or it gracefully blocks
    // (`youtube-embed-blocked`). For dQw4w9WgXcQ we expect blocked, but we
    // wait for the IFrame API onError to fire, which can take a few seconds.
    const fallback = page.getByTestId("youtube-watch-fallback");
    await expect(fallback).toBeVisible({ timeout: 15_000 });
    await expect(fallback).toHaveAttribute("href", /dQw4w9WgXcQ/);
    // The header "open source" affordance always points at watch_url.
    await expect(page.getByTestId("radio-open-source")).toHaveAttribute(
      "href",
      /dQw4w9WgXcQ/,
    );

    // 8. Discogs ontology enrichment surfaces a deeplink to master/96559.
    const discogsLink = page.getByTestId("radio-discogs-link");
    await expect(discogsLink).toBeVisible();
    await expect(discogsLink).toHaveAttribute(
      "href",
      /discogs\.com\/master\/96559/,
    );
    await expect(discogsLink).toContainText("master/96559");
  });

  test("desktop search bar accepts /play and opens the Radio app", async ({ page }) => {
    await page.goto("/?skipboot=1");

    const desktopSearch = page.getByTestId("desktop-search-input");
    await expect(desktopSearch).toBeVisible();
    await desktopSearch.fill(`/play ${PLAY_QUERY}`);
    await desktopSearch.press("Enter");

    const player = page.getByTestId("radio-player");
    await expect(player).toBeVisible();
    await expect(page.getByTestId("radio-title")).toHaveText(
      "Never Gonna Give You Up",
    );
    await expect(player).toHaveAttribute("data-source", "youtube");
  });

  test("backend resolves the same query directly", async ({ request }) => {
    const res = await request.post("/api/music/play/resolve", {
      data: { query: PLAY_QUERY, zone: "default" },
    });
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.tracks?.[0]?.title).toBe("Never Gonna Give You Up");
    expect(body.tracks?.[0]?.artist).toBe("Rick Astley");
    expect(["exact", "fuzzy", "demo_catalog"]).toContain(body.matched_via);
    // Discogs enrichment is best-effort: the master_id is always pinned even
    // when the live API call fails, so we can assert it unconditionally.
    expect(body.tracks?.[0]?.discogs?.master_id).toBe(96559);
    expect(body.tracks?.[0]?.discogs?.url).toMatch(
      /discogs\.com\/master\/96559/,
    );
  });
});
