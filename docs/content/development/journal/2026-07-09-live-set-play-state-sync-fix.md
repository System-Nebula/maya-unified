---
title: "Journal — Live-set player: YouTube play-state sync fix"
date: 2026-07-09
tags: [journal, dashboard, music-player, youtube]
---

# 2026-07-09 — Live-set player: control ↔ embedded-YouTube sync

Follow-up to the OTEL/DOM pass. Reported symptom: clicking our play button
didn't start the video and our controls didn't reflect the embedded YouTube
player's state. Diagnosed live in the browser; two distinct faults.

## Bug 1 — the state poll was killed the instant it started (root cause)
`apps/dashboard/js/mayaLiveSet.js` `createYtTransport().init().onReady` ran
`startPoll()` then `clearTimers()`, and `clearTimers()` cleared **both** the
audio-fallback timeout **and** the 500ms `pollTimer` that `startPoll()` had just
created. Net: the poll never ran, so `player.currentTime` never advanced and
`player.playing` was never reconciled from `getPlayerState()`.

Observed: on a working mount, `playing=true` (from `onStateChange`) but
`currentTime` frozen at 0 and `setCurrentIdx` stuck at 0 — video plays, our
progress bar / "TRACK n OF m" / tracklist highlight all frozen. That's the
"controls don't sync" report.

**Fix:** in `onReady`, cancel only the fallback timeout, then `startPoll()`.
Verified via a direct `YT.Player` on the real `#maya-yt-player` element:
`getCurrentTime()` advances 0→17.5s over `setInterval` — the exact poll
mechanism. (`setInterval` is not rAF-throttled, so the poll runs fine even in
the automation browser.)

## Bug 2 — our play button's `playVideo()` was autoplay-blocked
Our play button and the click-to-play overlay live in the **parent** frame.
`ytPlayer.playVideo()` via the IFrame API isn't counted as a user activation by
the cross-origin iframe's autoplay policy (which is engagement/MEI-based), so a
genuine click sometimes does nothing — while a click *inside* the iframe
(YouTube's own button) always works. Intermittent: it played on the first
attempt of a session, then stopped. The `cued`-state overlay also covers
YouTube's native button, so the user can get stuck.

**Fix:** on the user's play gesture, if plain `playVideo()` hasn't started
playback ~350ms later, retry **muted** (`mute()` + `playVideo()`, which is
always policy-allowed) and set `setMuted`, which surfaces a
"▶ MUTED — TAP TO UNMUTE" affordance (`unmuteSet()` → `_ytTransport.unMute()`).
The 350ms guard skips the retry when plain play already worked (checks
PLAYING/BUFFERING), so no regression to the normal case.

Also added `playsinline: 1` + `origin: window.location.origin` to the
`YT.Player` `playerVars` for reliable API-event delivery.

Verified live: clicking play with plain play blocked → `setMuted=true`, the
"TAP TO UNMUTE" button renders, and clicking it clears `setMuted`. The muted
retry firing confirms plain `playVideo()` was blocked.

## Files
- `apps/dashboard/js/mayaLiveSet.js` — poll fix; `playerVars`; muted-play retry
  in `play()`; `unMute()` added to the transport API.
- `apps/dashboard/js/mayaConversation.js` — `setMuted` state; `unmuteSet()`;
  reset `setMuted` in `_teardownSetTransport`.
- `apps/dashboard/conversation.html` — "TAP TO UNMUTE" button in the video wrap.
- `apps/dashboard/css/maya-player.css` — `.live-set-unmute` styles.

## Bug 3 — click-to-seek reset the playhead + selected track to the start
Surfaced by the Bug 1 fix (now that the poll runs): the poll did
`player.currentTime = getCurrentTime() ?? 0` unconditionally. `seekToSeconds`
sets `currentTime = sec` optimistically, but within 500ms the poll overwrote it
— and when the video is cued/paused (autoplay-blocked, i.e. right after a
click-seek), YouTube's `getCurrentTime()` returns **0**. Since `setCurrentIdx`
(`currentEntryIndex(setEntries, currentTime)`) and `setProgressPct` are derived
from `currentTime`, the playhead and highlighted track snapped back to the start
while the video sat at the seeked frame.

**Fix:** the poll updates `currentTime` from the player only while state is
`PLAYING`; when paused/cued/unstarted it leaves `currentTime` alone, so the
optimistic seek value holds until playback resumes there. Verified live: clicked
track 9 on a cued video → `currentTime=844` and `setCurrentIdx=8` held across ~6
poll cycles (previously dropped to 0 within one), with the waveform playhead,
"TRACK 9 OF 26" and the row highlight all staying put.

## Environment note (automation browser)
The mount pipeline (`deferYtMount` + `mountWhenReady`) is **rAF-gated**, and
`requestAnimationFrame` does not fire in the offscreen automation browser even
when `document.visibilityState === 'visible'` (confirmed: `Alpine.nextTick`
fired but the following `requestAnimationFrame` never did). So the player only
mounts there while actively painting (e.g. taking screenshots); on a real
foreground browser rAF fires and it mounts normally. After many mount/destroy
cycles the automation browser also stops sustaining YouTube playback, so
**actual muted-playback start + `currentTime` advancing on the real transport
should be confirmed on a real browser** — the poll mechanism itself is proven.
Possible follow-up: make the mount tolerate rAF starvation (setTimeout fallback)
so a backgrounded tab during load still mounts.
