import { expect, test } from "@playwright/test";

const ANDREA_URL =
  "https://youtu.be/u1NHX9FcHVw?list=RDu1NHX9FcHVw";

/** Minimal Andrea Botez live-set artifact for UI contract tests (no network). */
function andreaLiveSetArtifact() {
  const setKey = "yt:u1NHX9FcHVw";
  const containerUrl = "https://www.youtube.com/watch?v=u1NHX9FcHVw";
  const entries = [
    { position: 1, start_seconds: 0, end_seconds: 102, label: "Hard Bounce", title: "Hard Bounce", artist: "Hard Bounce" },
    {
      position: 4,
      start_seconds: 4 * 60 + 34,
      end_seconds: 6 * 60 + 42,
      label: "Brisa Bailo Sola - Mha iri Remix",
      title: "Brisa Bailo Sola - Mha iri Remix",
    },
    {
      position: 9,
      start_seconds: 14 * 60 + 4,
      end_seconds: 16 * 60 + 50,
      label: "Vall Du Son - Play",
      artist: "Vall Du Son",
      title: "Play",
    },
  ];
  const tracks = entries.map((e) => ({
    title: e.label,
    query: containerUrl,
    src: `/api/media/stream?q=${encodeURIComponent(containerUrl)}`,
    start_offset: e.start_seconds,
    end_offset: e.end_seconds,
    position: e.position,
    play_mode: "seek",
    set_key: setKey,
  }));
  return {
    type: "playlist",
    presentation: "set",
    mode: "live_set",
    title: "HIGH ENERGY TECHNO MIX | Andrea Botez",
    url: containerUrl,
    set_key: setKey,
    set_id: "u1NHX9FcHVw",
    container_url: containerUrl,
    container_schema: "yt",
    video_id: "u1NHX9FcHVw",
    duration_seconds: 3330,
    entries,
    tracks,
  };
}

test.describe("Dashboard live set /play presentation", () => {
  test.beforeEach(async ({ page }) => {
    // Keep the in-page YT mock — block the real iframe_api script from overwriting it.
    await page.route(/youtube\.com\/iframe_api/, (route) => route.abort());
    await page.addInitScript(() => {
      (window as unknown as { __mockYtTime: number }).__mockYtTime = 0;
      (window as unknown as { __mockYtPlayCalls: number }).__mockYtPlayCalls = 0;
      (window as unknown as { __mockYtPauseCalls: number }).__mockYtPauseCalls = 0;
      (window as unknown as { __mockYtAutoplayBlocked: boolean }).__mockYtAutoplayBlocked = false;
      (window as unknown as { YT: unknown }).YT = {
        Player: function Player(
          _targetId: string,
          opts: {
            events?: {
              onReady?: () => void;
              onStateChange?: (ev: { data: number }) => void;
            };
          },
        ) {
          let state = -1; // UNSTARTED
          let isMuted = false;
          let interval: number | null = null;

          const changeState = (s: number) => {
            state = s;
            opts.events?.onStateChange?.({ data: s });
            if (s === 1 && !interval) {
              interval = window.setInterval(() => {
                (window as unknown as { __mockYtTime: number }).__mockYtTime += 0.5;
              }, 500);
            } else if (s !== 1 && interval) {
              clearInterval(interval);
              interval = null;
            }
          };

          const api = {
            seekTo: (seconds: number) => {
              (window as unknown as { __mockYtTime: number }).__mockYtTime = seconds;
            },
            playVideo: () => {
              (window as unknown as { __mockYtPlayCalls: number }).__mockYtPlayCalls += 1;
              if ((window as unknown as { __mockYtAutoplayBlocked: boolean }).__mockYtAutoplayBlocked) {
                return;
              }
              changeState(1);
            },
            pauseVideo: () => {
              (window as unknown as { __mockYtPauseCalls: number }).__mockYtPauseCalls += 1;
              changeState(2);
            },
            mute: () => {
              isMuted = true;
            },
            unMute: () => {
              isMuted = false;
            },
            getPlayerState: () => state,
            getCurrentTime: () => {
              const st = state;
              const PS = (window as unknown as { YT: { PlayerState: Record<string, number> } }).YT.PlayerState;
              // While cued/unstarted the real API often reports 0 even after seek.
              if (st === PS.CUED || st === PS.UNSTARTED) return 0;
              return (window as unknown as { __mockYtTime: number }).__mockYtTime || 0;
            },
            destroy: () => {
              if (interval) clearInterval(interval);
            },
          };
          setTimeout(() => {
            opts.events?.onReady?.();
            changeState(5); // CUED
          }, 0);
          return api;
        },
        PlayerState: { UNSTARTED: -1, PLAYING: 1, PAUSED: 2, BUFFERING: 3, CUED: 5 },
      };
      Object.defineProperty(window, "YT", {
        value: (window as unknown as { YT: unknown }).YT,
        writable: false,
        configurable: true,
      });
    });
  });

  async function loginAsDefault(page: import("@playwright/test").Page) {
    await page.goto("/login");
    await page.locator("#login-email").fill("admin");
    await page.locator("#login-password").fill("admin");
    await page.locator("#login-submit").click();
    await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 15_000 });
  }

  async function loadAndreaSet(page: import("@playwright/test").Page) {
    await loginAsDefault(page);
    await page.goto("/");
    await page.waitForFunction(
      () => typeof (window as unknown as { Alpine?: { store?: (n: string) => unknown } }).Alpine?.store === "function",
    );
    await page.evaluate((artifact) => {
      const Alpine = (window as unknown as { Alpine: { store: (n: string) => { load: (a: unknown) => void } } }).Alpine;
      Alpine.store("mayaPlayer").load(artifact, { autoplay: false });
    }, andreaLiveSetArtifact());

    await expect(page.getByTestId("live-set-viewer")).toBeVisible({ timeout: 15_000 });

    await page.waitForFunction(
      () => {
        const player = (window as unknown as { Alpine: { store: (n: string) => Record<string, unknown> } }).Alpine.store(
          "mayaPlayer",
        );
        const transport = player._ytTransport as { isReady?: () => boolean } | null | undefined;
        return transport?.isReady?.() === true || (player.setYtReady === true && player.setUseYt === true);
      },
      null,
      { timeout: 15_000 },
    );
  }

  test("loads live set viewer and seeks on tracklist click", async ({ page }) => {
    await loadAndreaSet(page);

    const viewer = page.getByTestId("live-set-viewer");
    await expect(page.getByTestId("md-player-sticky")).toBeVisible();
    await expect(viewer).toBeVisible();

    const tracklist = page.getByTestId("live-set-tracklist");
    await expect(tracklist).toBeVisible();

    const state = await page.evaluate(() => {
      const player = (window as unknown as { Alpine: { store: (n: string) => Record<string, unknown> } }).Alpine.store(
        "mayaPlayer",
      );
      const transport = player._ytTransport as { isReady?: () => boolean } | null | undefined;
      return {
        presentation: player.presentation,
        mode: player.mode,
        setUseYt: player.setUseYt,
        ytTransportReady: transport?.isReady?.() === true,
        entryCount: (player.setEntries as unknown[])?.length,
      };
    });

    expect(state.presentation).toBe("set");
    expect(state.mode).toBe("live_set");
    expect(state.setUseYt === true || state.ytTransportReady === true).toBe(true);
    expect(state.entryCount).toBe(3);

    const nowPlaying = page.locator(".live-set-now-title");
    await expect(nowPlaying).toHaveText("Hard Bounce");

    await expect(page.locator(".mp-live-set .mp-queue-clear")).toHaveCount(1);

    await page.evaluate(() => {
      const player = (window as unknown as { Alpine: { store: (n: string) => { setEntries: unknown[]; seekSetEntry: (e: unknown) => void } } }).Alpine.store(
        "mayaPlayer",
      );
      player.seekSetEntry(player.setEntries[2]);
    });

    await expect(nowPlaying).toHaveText("Vall Du Son - Play");

    await page.evaluate(() => {
      const player = (window as unknown as { Alpine: { store: (n: string) => { setEntries: unknown[]; seekSetEntry: (e: unknown) => void } } }).Alpine.store(
        "mayaPlayer",
      );
      player.seekSetEntry(player.setEntries[1]);
    });

    const currentTime = await page.evaluate(
      () => (window as unknown as { Alpine: { store: (n: string) => { currentTime: number } } }).Alpine.store("mayaPlayer").currentTime,
    );
    expect(currentTime).toBeGreaterThanOrEqual(4 * 60 + 30);
    expect(currentTime).toBeLessThanOrEqual(4 * 60 + 40);

    const mockYtTime = await page.evaluate(
      () => (window as unknown as { __mockYtTime: number }).__mockYtTime,
    );
    expect(mockYtTime).toBeGreaterThanOrEqual(4 * 60 + 30);
  });

  test("custom play/pause controls drive the YouTube transport", async ({ page }) => {
    await loadAndreaSet(page);

    const playBtn = page.locator(".mp-live-set .player-btn-play");
    await expect(playBtn).toBeVisible();

    await playBtn.click();

    await page.waitForFunction(
      () => (window as unknown as { Alpine: { store: (n: string) => { playing: boolean } } }).Alpine.store("mayaPlayer").playing === true,
    );

    const playCalls = await page.evaluate(
      () => (window as unknown as { __mockYtPlayCalls: number }).__mockYtPlayCalls,
    );
    expect(playCalls).toBeGreaterThanOrEqual(1);

    await playBtn.click();

    await page.waitForFunction(
      () => (window as unknown as { Alpine: { store: (n: string) => { playing: boolean } } }).Alpine.store("mayaPlayer").playing === false,
    );

    const pauseCalls = await page.evaluate(
      () => (window as unknown as { __mockYtPauseCalls: number }).__mockYtPauseCalls,
    );
    expect(pauseCalls).toBeGreaterThanOrEqual(1);
  });

  test("seek position holds while cued (autoplay blocked)", async ({ page }) => {
    await page.addInitScript(() => {
      (window as unknown as { __mockYtAutoplayBlocked: boolean }).__mockYtAutoplayBlocked = true;
    });
    await loadAndreaSet(page);

    const track9Sec = 14 * 60 + 4;
    await page.evaluate(() => {
      const player = (window as unknown as { Alpine: { store: (n: string) => { setEntries: { start_seconds: number }[]; seekSetEntry: (e: unknown) => void } } }).Alpine.store(
        "mayaPlayer",
      );
      player.seekSetEntry(player.setEntries[2]);
    });

    await page.waitForFunction(
      (sec) =>
        (window as unknown as { Alpine: { store: (n: string) => { currentTime: number } } }).Alpine.store("mayaPlayer")
          .currentTime >= sec - 1,
      track9Sec,
    );

    // Wait ~3 poll cycles — previously a 3s timeout cleared the seek guard and snapped to 0.
    await page.waitForTimeout(1600);

    const currentTime = await page.evaluate(
      () => (window as unknown as { Alpine: { store: (n: string) => { currentTime: number } } }).Alpine.store("mayaPlayer").currentTime,
    );
    expect(currentTime).toBeGreaterThanOrEqual(track9Sec - 1);
    expect(currentTime).toBeLessThanOrEqual(track9Sec + 1);

    const setCurrentIdx = await page.evaluate(
      () => (window as unknown as { Alpine: { store: (n: string) => Record<string, unknown> } }).Alpine.store("mayaPlayer").setCurrentIdx,
    );
    expect(setCurrentIdx).toBe(2);
  });

  test("currentTime advances while playing", async ({ page }) => {
    await loadAndreaSet(page);

    await page.locator(".mp-live-set .player-btn-play").click();
    await page.waitForFunction(
      () => (window as unknown as { Alpine: { store: (n: string) => { playing: boolean } } }).Alpine.store("mayaPlayer").playing === true,
    );

    const t0 = await page.evaluate(
      () => (window as unknown as { Alpine: { store: (n: string) => { currentTime: number } } }).Alpine.store("mayaPlayer").currentTime,
    );
    await page.waitForTimeout(1200);
    const t1 = await page.evaluate(
      () => (window as unknown as { Alpine: { store: (n: string) => { currentTime: number } } }).Alpine.store("mayaPlayer").currentTime,
    );
    expect(t1).toBeGreaterThan(t0);
  });

  test("conversation /play /play queues live set via chat bridge", async ({ page, request }) => {
    const status = await request.get("/api/voice/agent/status");
    test.skip(!status.ok(), "requires unified gateway with voice agent routes");

    await page.goto("/conversation");
    await page.waitForFunction(() => {
      const Alpine = (window as unknown as { Alpine?: { store?: (n: string) => Record<string, unknown> } }).Alpine;
      const shell = Alpine?.store?.("mayaShell");
      const caps = (shell?.capabilities as Record<string, boolean> | undefined) || {};
      return caps.text_chat === true || shell?.llmReady === true;
    }, null, { timeout: 30_000 });

    const textarea = page.locator(".md-composer textarea.mv-input");
    await textarea.fill(`/play /play ${ANDREA_URL}`);
    await page.getByRole("button", { name: "Send" }).click();

    await expect(page.getByText(/26 tracks.*live set|Loaded.*26 tracks/)).toBeVisible({ timeout: 90_000 });
    await expect(page.getByText(/Now playing.*\/play/)).toHaveCount(0);
    await expect(page.getByTestId("md-player-sticky")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("live-set-viewer")).toBeVisible({ timeout: 15_000 });

    const debug = await page.evaluate(() => {
      const fn = (window as unknown as { mayaLiveSetDebug?: () => Record<string, unknown> }).mayaLiveSetDebug;
      return fn?.() ?? null;
    });
    expect(debug?.presentation).toBe("set");
    expect(debug?.setEntries).toBe(26);
    expect(debug?.active).toBe(true);
  });
});
