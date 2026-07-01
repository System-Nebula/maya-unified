# Demo audio

The public-boundary policy keeps copyrighted previews out of git.

For local development the gateway returns `preview_url=/demo/rick-roll-preview.mp3`
but ships no audio binary. Either drop a CC0/public-domain clip here
(name it `rick-roll-preview.mp3`) or override `MAYA_MUSIC_PREVIEW_URL` on the
gateway.

The Playwright e2e suite does not require a real audio file; it asserts on
window/title/control state, not on actual decoded playback.
