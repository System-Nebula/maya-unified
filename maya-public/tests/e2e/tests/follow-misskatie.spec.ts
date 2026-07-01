import { expect, test } from "@playwright/test";

/**
 * End-to-end coverage of the Following management panel.
 *
 * Requires a running Postgres reachable at the gateway's DATABASE_URL with
 * the `follow_graph_20260525` alembic migration applied. The webServer in
 * playwright.config.ts boots the gateway via `uv run maya-gateway`; ensure
 * Postgres is up before running this suite.
 *
 * State isolation: every run uses a fresh, timestamped slug so re-running
 * the suite doesn't trip the unique-slug-while-live partial index.
 */

const RUN_ID = String(Date.now());
const SLUG = `e2e-misskatie-${RUN_ID}`;
const DISPLAY_NAME = `MissKatie E2E ${RUN_ID}`;
const YT_URL = "https://www.youtube.com/@MissKatie";
const IG_URL = "https://instagram.com/heymisskatie";
const TT_URL = "https://tiktok.com/@heymisskatiee";

test.describe("Following — operator entity tree", () => {
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

  test("backend builds a tree with PERSON follow + CHANNEL-level mute override", async ({
    request,
  }) => {
    // 1. Resolve a YT URL → ChannelRef preview, no network fetch required.
    const resolveRes = await request.post("/api/follow/resolve", {
      data: { input: YT_URL },
    });
    expect(resolveRes.status()).toBe(200);
    const resolved = await resolveRes.json();
    expect(resolved.channel.platform).toBe("youtube");
    expect(resolved.channel.handle).toBe("@MissKatie");

    // 2. Create the umbrella Person entity.
    const personRes = await request.post("/api/follow/persons", {
      data: {
        slug: SLUG,
        display_name: DISPLAY_NAME,
        kind: "REAL",
      },
    });
    expect(personRes.status()).toBe(200);
    const person = await personRes.json();
    expect(person.slug).toBe(SLUG);

    // 3. Attach 3 channels via the URL → resolve flow.
    for (const url of [YT_URL, IG_URL, TT_URL]) {
      const attachRes = await request.post(
        `/api/follow/persons/${person.id}/channels`,
        { data: { resolve: { input: url } } },
      );
      expect(attachRes.status()).toBe(200);
    }

    // 4. Follow at the PERSON level.
    const personFollowRes = await request.post("/api/follow/follows", {
      data: {
        subject_type: "PERSON",
        subject_id: person.id,
        cadence: "weekly",
      },
    });
    expect(personFollowRes.status()).toBe(200);

    // 5. Fetch the tree and confirm all three channels report tracking via
    //    inheritance from the PERSON follow.
    let treeRes = await request.get("/api/follow/tree?operator_id=local");
    expect(treeRes.status()).toBe(200);
    let tree = await treeRes.json();
    const node = tree.nodes.find((n: { person: { id: string } }) =>
      n.person.id === person.id,
    );
    expect(node).toBeTruthy();
    expect(node.channels).toHaveLength(3);
    for (const ch of node.channels) {
      expect(ch.effective.tracking).toBe(true);
      expect(ch.effective.source).toBe("PERSON");
    }

    // 6. Mute the Instagram channel via a CHANNEL-level Follow override.
    const igChannel = node.channels.find(
      (c: { channel: { platform: string } }) => c.channel.platform === "instagram",
    );
    expect(igChannel).toBeTruthy();
    const muteRes = await request.post("/api/follow/follows", {
      data: {
        subject_type: "CHANNEL",
        subject_id: igChannel.channel.id,
        muted: true,
      },
    });
    expect(muteRes.status()).toBe(200);

    // 7. The tree now reports Instagram as muted via CHANNEL source, while
    //    YT and TikTok continue to inherit from the PERSON row.
    treeRes = await request.get("/api/follow/tree?operator_id=local");
    tree = await treeRes.json();
    const updated = tree.nodes.find((n: { person: { id: string } }) =>
      n.person.id === person.id,
    );
    const byPlatform: Record<string, { effective: { tracking: boolean; source: string; muted: boolean } }> = {};
    for (const c of updated.channels) {
      byPlatform[c.channel.platform] = c;
    }
    expect(byPlatform.youtube.effective.tracking).toBe(true);
    expect(byPlatform.youtube.effective.source).toBe("PERSON");
    expect(byPlatform.instagram.effective.tracking).toBe(false);
    expect(byPlatform.instagram.effective.source).toBe("CHANNEL");
    expect(byPlatform.instagram.effective.muted).toBe(true);
    expect(byPlatform.tiktok.effective.tracking).toBe(true);
    expect(byPlatform.tiktok.effective.source).toBe("PERSON");
  });

  test("Following app renders the tree and respects the mute override", async ({
    page,
    request,
  }) => {
    // Pre-seed via the API so the UI test focuses on rendering, not setup.
    const seedSlug = `e2e-ui-${RUN_ID}`;
    const personRes = await request.post("/api/follow/persons", {
      data: {
        slug: seedSlug,
        display_name: `MissKatie UI ${RUN_ID}`,
        kind: "REAL",
      },
    });
    const person = await personRes.json();

    await request.post(`/api/follow/persons/${person.id}/channels`, {
      data: { resolve: { input: YT_URL } },
    });
    await request.post(`/api/follow/persons/${person.id}/channels`, {
      data: { resolve: { input: IG_URL } },
    });
    await request.post(`/api/follow/persons/${person.id}/channels`, {
      data: { resolve: { input: TT_URL } },
    });
    await request.post("/api/follow/follows", {
      data: { subject_type: "PERSON", subject_id: person.id },
    });

    const tree = await (
      await request.get("/api/follow/tree?operator_id=local")
    ).json();
    const node = tree.nodes.find(
      (n: { person: { id: string } }) => n.person.id === person.id,
    );
    const igChannelId = node.channels.find(
      (c: { channel: { platform: string } }) => c.channel.platform === "instagram",
    ).channel.id;
    await request.post("/api/follow/follows", {
      data: { subject_type: "CHANNEL", subject_id: igChannelId, muted: true },
    });

    // Open the Homepage and launch the Following app via the Launcher.
    await page.goto("/?skipboot=1");
    const launcherInput = page.getByTestId("launcher-input");
    await page.keyboard.press("Control+Alt+KeyK");
    await expect(launcherInput).toBeVisible();
    await launcherInput.fill("Following");
    await page.keyboard.press("Enter");
    await expect(launcherInput).toBeHidden();

    const app = page.getByTestId("following-app");
    await expect(app).toBeVisible();

    // The seeded person row is rendered.
    const personRow = page.locator(`[data-person-id="${person.id}"]`);
    await expect(personRow).toBeVisible();
    await expect(
      personRow.getByTestId("follow-person-toggle-follow"),
    ).toHaveAttribute("data-following", "true");

    // Expand to reveal channel rows.
    await personRow.getByTestId("follow-person-toggle").click();

    const channelRows = personRow
      .locator('[data-testid="follow-channel-list"]')
      .locator('[data-testid="follow-channel"]');
    await expect(channelRows).toHaveCount(3);

    const ig = personRow.locator(`[data-channel-id="${igChannelId}"]`);
    await expect(ig).toHaveAttribute("data-tracking", "false");
    await expect(ig).toHaveAttribute("data-effective-source", "CHANNEL");
    await expect(
      ig.getByTestId("follow-channel-effective"),
    ).toHaveAttribute("data-state", "muted");

    // YT and TikTok inherit from the person follow.
    for (const platform of ["youtube", "tiktok"]) {
      const row = personRow.locator(`[data-platform="${platform}"]`);
      await expect(row).toHaveAttribute("data-tracking", "true");
      await expect(row).toHaveAttribute("data-effective-source", "PERSON");
    }
  });
});
