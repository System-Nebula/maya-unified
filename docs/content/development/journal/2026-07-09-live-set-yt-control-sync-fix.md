---
title: "Journal — Live-set player: custom controls → YouTube embed sync"
date: 2026-07-09
tags: [journal, dashboard, music-player, youtube]
---

# 2026-07-09 — Live-set player: custom controls → YouTube embed sync

Follow-up to the Jul 9 play-state sync pass. Symptom: **seek worked** (tracklist +
waveform jumped the embed) but **custom play/pause did not drive the YouTube
player**. Regression from inconsistent transport routing and stacked playerVars /
play() changes.

## Root cause

| Action | Guard (before) | Effect |
|--------|----------------|--------|
| Seek | `_ytTransport` only | Always hit YouTube |
| Play/pause toggle | `_ytTransport && setYtReady` | Could fall through to hidden `<audio>` |
| pause/resume | `setUseYt && _ytTransport` | Same desync |

When `setYtReady` / `setUseYt` desynced from the actual iframe player, seek
still worked but toggle routed to the audio element.

Additional regressions from the prior session: `playerVars.origin` (breaks IFrame
API command delivery on some setups) and a 350ms muted-play retry that masked
failures.

## Fix

**`apps/dashboard/js/mayaLiveSet.js`**
- Added `isReady()` / `getPlayerState()` on the transport API.
- Simplified `play()` / `pause()` — synchronous `playVideo()` / `pauseVideo()`,
  removed `origin` from `playerVars`, removed muted-fallback retry.
- Poll: advance `currentTime` while `PLAYING`; seek-guard holds optimistic time
  when not playing (no 3s timeout snap-back); `onStateChange` owns `playing` state.
- `mountWhenReady`: mount when `#maya-yt-player` exists (not `offsetParent`);
  setTimeout poll for headless/rAF-starved environments.

**`apps/dashboard/js/mayaConversation.js`**
- `_ytControlsActive()` — single guard: `isSetPresentation && _ytTransport.isReady()`.
- `toggle`, `play`, `pause`, `resume`, `seekSetEntry`, `seekTo` all route through it.
- `deferYtMount`: setTimeout fallback when rAF stalls.
- `mayaLiveSetDebug()` exposes `ytTransportReady`.

**`tests/e2e/tests/play-andrea-live-set.spec.ts`**
- Stronger YT mock (stateful `getPlayerState`, advancing clock, autoplay-block mode).
- Block real `iframe_api` script; lock mock with `Object.defineProperty`.
- New tests: outbound play/pause, seek-hold while cued, currentTime advances.

## Verification

```bash
MAYA_E2E_UNIFIED=1 MAYA_E2E_FIXTURES=1 MAYA_GATEWAY_PORT=8765 \
  npx playwright test play-andrea-live-set.spec.ts
```

Four core tests green (loads + seek, play/pause controls, seek-hold, time advance).

Manual check on real browser (:8090, live YouTube): `/play` Andrea URL → custom
play/pause drives embed; track/waveform seek holds position; playhead advances
while playing. Use `window.mayaLiveSetDebug()` to confirm `ytTransportReady`.
