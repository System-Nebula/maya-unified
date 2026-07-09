---
title: "Journal — Live-set player: OTEL trace correlation + DOM verification"
date: 2026-07-09
tags: [journal, dashboard, music-player, observability, otel]
---

# 2026-07-09 — Live-set player: end-to-end OTEL trace + rendered-DOM verify

Follow-up to [2026-07-08](2026-07-08-live-set-player-and-clear-loop.md). The
player fixes, responsive layout, and OTEL wiring had been implemented in a
parallel session; this pass verified them end-to-end and cleared the remaining
test failures.

## What was verified

### 1. `/play` "Play" title bug — root cause found, fix confirmed live
Not a backend fallback bug. Track 9 of the Andrea Botez set is literally
`14:04 Vall Du Son - Play`. The parser splits it into
`artist="Vall Du Son", title="Play", label="Vall Du Son - Play"`, and the old
now-playing binding rendered only `entry.title` → the bare word **"Play"**.

Fix (already in tree): `normalizeEntry` carries `artist`; a `setNowPlayingLabel`
getter prefers `label` (or `artist — title`) and falls back to the set title.
Confirmed in the running dashboard: clicking track 9 updates
`setCurrentIdx → 8`, `setNowPlayingLabel → "Vall Du Son - Play"`,
`entryArtist="Vall Du Son"`, `start_seconds=844`. Now-playing header reads
**"Vall Du Son - Play · 14:04"**.

### 2. End-to-end OTEL trace (the "correlate events" ask)
Enabled OTEL (`VA_OTEL_ENABLED=1`, `OTEL_SERVICE_NAME=maya-unified-gateway`,
`VA_OTEL_LOGS=0`), started the bundled Jaeger compose, and confirmed a single
trace for a `/play`, keyed to the browser-supplied `traceparent`:

```
cmd.dispatch            corr=c_…  cmd.id=play
  play.build_playlist   corr=c_…  presentation=set  track_count=26
    music.url_index     corr=c_…
      music.fetch_document
      music.tracklist_parse
  player.broadcast      corr=c_…  presentation=set  track_count=26
```

Every span carries `chat.corr_id` (via OTEL baggage attached in the dispatcher),
and the trace id equals the frontend `traceparent` — so the middleware extraction
makes the whole backend chain a child of the browser-initiated trace. Jaeger UI:
http://localhost:16686 (service `maya-unified-gateway`).

Note: Jaeger's OTLP endpoint only accepts **traces** — log export returns
`UNIMPLEMENTED`, hence `VA_OTEL_LOGS=0`. Backend needs the `otel` extra installed
(`uv sync --extra otel`); it was missing and caused a silent
"SDK not installed" warning on first start.

### 3. Rendered DOM (Chrome, live)
- **Responsive layout works** via container query on `.mp-live-set`
  (`container-type: inline-size`): body is `row` (side-by-side, video/tracklist)
  at 1276px, flips to `column` (stacked, video centered ≤32rem, tracklist
  full-width) when constrained below the 900px breakpoint.
- Tracklist fills the column and scrolls all 26 rows (the 1-row collapse and the
  duplicate `18rem`/`14rem` max-heights are gone).
- Exactly **one** Clear button; single progress indicator ("SET PROGRESS ·
  TRACK n OF 26"); no stray `TRK` strip in set mode.
- Video iframe mounts and is correctly sized (739×416, ~16/9 — `aspect-ratio`
  fix; the YT API replaces `#maya-yt-player` with the iframe). Real poster loads.
- Click-to-seek routes through the transport (`setCurrentIdx` + now-playing
  update).

### 4. Tests
Fixed two `tests/test_cmd_registry.py` failures caused by the parallel
play.py/clear changes:
- `test_dispatch_play_dashboard_emits_playlist`: `/play` now (intentionally)
  attaches the playlist artifact — assertion updated to expect it.
- `test_player_cache_clear_removes_state`: added an autouse `_player_cache`
  reset fixture (state leaked between tests via the module-level cache).

Green: `tests/test_cmd_registry.py`, `tests/test_cmd_chat_bridge.py`,
`apps/gateway/tests/` (excluding the pre-existing `test_operator_auth.py`
failures, which are unrelated — a mocked-session regression from `a325c86`).

## Not yet verified / follow-ups
- **Live video playback + play/pause state sync**: the sandboxed automation
  browser loads the YouTube poster but will not start the stream (no JS/onError,
  embed healthy — an environment restriction). The play-state fix
  (`onStateChange` as single source of truth, poll reconciliation) therefore
  couldn't be exercised against a *playing* video here. Confirm on a real browser
  that: clicking our play button starts/pauses, and clicking inside the YouTube
  iframe directly is reflected in our play/pause icon. First-play may still
  require one click on YouTube's own button (cross-origin autoplay policy) — the
  CUED overlay is meant to cover this.
- **Playwright e2e** (`tests/e2e/tests/play-andrea-live-set.spec.ts`) still needs
  a local run (no `node`/`npx` in the work shell). Run against a
  `MAYA_E2E_FIXTURES=1` gateway.

## Ops notes
- `packages/maya-db/src/maya_db/connection.py:23` binds the async engine at
  **import time** via a module-level `get_engine()`. If anything imports
  `maya_db.connection` before `.env` loads it silently pins `DEFAULT_URL`
  (`localhost:5432/maya_public`). `launch.py` load order is currently safe, but
  it's fragile — worth making the factory lazy.
- A first gateway start hit a transient DB `ConnectionRefused` during the heavy
  TTS-load startup window; a clean restart resolved it.
