---
title: "Journal — Live-set player + player.control:clear loop"
date: 2026-07-08
tags: [journal, dashboard, music-player]
---

# 2026-07-08 — `/play` live-set player: clear-loop fix + UI restore

## Symptom

`/play <youtube-url>` in the Maya dashboard chat returned the correct text
("Loaded u1NHX9FcHVw — 26 tracks (live set).") but **no player opened and no
tracklist appeared**. Earlier in the session the player did come up, but the
live-set view had regressed against the Figma prototype (misaligned controls,
wrong queue gutter, missing volume slider + waveform, dead click-to-seek).

## Root cause (the "no player opens" bug)

A **`player.control:clear` broadcast feedback loop**:

1. client `clear()` → `POST /api/media/player/clear`
2. server `clear_player_and_broadcast()` → broadcasts `player.control:clear`
3. that SSE event returns to the client → `_applyAgentEvent` → `control("clear")`
   → `clear()` → `POST` → back to step 1 (amplified across tabs)

The gateway log showed **140,857** `POST /api/media/player/clear` calls still
flooding in from two tabs. Every `/play` *did* load the player
(`play_loaded artifact_attached=True … track_count=26` in the log), but the
running clear-storm set `active=false` a fraction of a second later. Pre-existing
migration regression, unrelated to the layout work.

## Changes

Frontend — `apps/dashboard/`:
- `js/mayaConversation.js`
  - Split `clear()` into `clearLocal()` (local teardown, no network) + `clear()`
    (local + one POST). Inbound `control("clear")` now calls `clearLocal()` — no
    echo, no loop.
  - `seekTo()` gained a YouTube branch; `seekSetEntry()` routes to the YT
    transport whenever it exists (not gated on `setUseYt`) — fixes click-to-seek.
  - `_loadSetPresentation()` made idempotent per `set_key` (kills 3× transport
    churn from the redundant broadcast paths); added `setNext()`/`setPrev()`; and
    `onReady` pauses fallback audio to avoid double-audio on self-heal.
- `conversation.html` — restructured `.mp-live-set` to the stacked layout
  (centered video on top; waveform progress bar via `mayaWaveform()`;
  prev/play/next + right-aligned `.mp-volume-inline` slider; full-width tracklist
  below).
- `css/maya-player.css` — stacked body, centered 32rem video, shared padding so
  embed + controls align, unified tracklist gutter, sized waveform, volume slider
  visible in all themes.
- `js/mayaLiveSet.js` — relaxed YT fallback timing (8s, then 10s post-mount) so a
  slow `onReady` doesn't spuriously drop to audio-fallback.

Backend — `services/dashboard/player.py`:
- `clear_player_and_broadcast()` now only broadcasts when there was actually a
  player to clear → repeated clears are idempotent (defense-in-depth; also calms
  already-open stale tabs).

## Verification

- Syntax/compile clean (deno parse for JS, `py_compile` for Python).
- Backend tests: 18 passed; the one failure (`test_run_long_cmd_imagine_schedules_remark`)
  is an `/imagine` remark test unrelated to these changes. `apps/maya-gateway`
  package test errors on collection (needs its own env — `maya_gateway` not
  installed in the root venv).
- Browser (unauthenticated tab, so validated via store + logs rather than a full
  click-through):
  - Layout renders stacked; volume slider `display:flex`; 44px waveform canvas;
    tracklist head/rows aligned at 16px.
  - Seek routes to YT: `seekSetEntry(#3)` → `currentTime` 240s; `seekTo(0.5)` →
    11970s.
  - Loop broken: `control('clear')` → **0** POSTs; user `clear()` → **1** POST.
- Gateway **restarted** on :8090 (matching `MAYA_E2E_FIXTURES=1 uv run python
  launch.py`); startup clean; **0** `/player/clear` POSTs since restart.

## Status

- Gateway restarted with all fixes live (running with `--reload` / WatchFiles).
- Nothing committed — working-tree changes only:
  `apps/dashboard/js/mayaConversation.js`, `apps/dashboard/js/mayaLiveSet.js`,
  `apps/dashboard/conversation.html`, `apps/dashboard/css/maya-player.css`,
  `services/dashboard/player.py`.

## Next

- Reload dashboard tab(s) to pick up the fixed frontend JS, then run
  `/play https://youtu.be/u1NHX9FcHVw?list=RDu1NHX9FcHVw` and confirm the player
  opens/stays with video + waveform + volume + clickable tracklist.
- Full authenticated end-to-end `/play` → SSE → player-stays flow still to be
  confirmed in the browser (automation tab was unauthenticated → API 401).
- Then commit.
