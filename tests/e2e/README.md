# Maya Public — e2e tests

Playwright suite for the Homepage + Maya Gateway. Validates the core
`/play <query>` flow against the demo resolver, plus a direct backend smoke
test of `/api/music/play/resolve`.

## Toolchain

JS deps are managed with **bun**. Drop into a shell with it if needed:

```bash
nix-shell -p bun python3 uv
```

## Install

```bash
# from repo root
make e2e-install        # bun install
```

…or from this directory:

```bash
bun install
```

> On NixOS, the chromium binary comes from `playwright-driver.browsers`
> in nixpkgs (the upstream Playwright download is a generic-Linux binary
> and won't run). `make e2e-test` arranges this automatically.

## Run

```bash
make e2e-test
```

If you'd rather run it by hand:

```bash
nix-shell -p bun python313 uv playwright-driver.browsers --run '
  export PLAYWRIGHT_BROWSERS_PATH="$buildInputs"
  export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
  bun x playwright test
'
```

The `webServer` block in `playwright.config.ts` boots `uv run maya-gateway`
on port 8765 for you, so the gateway doesn't need to be running already.

The Playwright config boots `uv run maya-gateway` on port 8765 via its
`webServer` block, so you don't need to start it manually. The gateway
serves the pre-built Homepage from
`apps/maya-gateway/src/maya_gateway/static/`, which is produced by
`make homepage-deploy`.

## What's covered

- `play-rick-astley.spec.ts`
  - Opens the launcher (`Ctrl+Alt+K`)
  - Types `/play Rick Astley - Never Gonna Give You Up`
  - Asserts the RadioPlayer window mounts with the right title / artist /
    `matched_via` and the play button is enabled
  - Calls `POST /api/music/play/resolve` directly and asserts the demo
    catalog returns the Rick Astley track

## Notes

- The suite skips the BootScreen animation via the `?skipboot=1` query
  param (see `App.tsx`).
- `localStorage`/`sessionStorage` are cleared before each test so the
  zustand-persisted lock/workspace state doesn't bleed across runs.
- Only `data-testid` selectors are used for app-owned UI affordances:
  `launcher-input`, `radio-player`, `radio-title`, `radio-artist`,
  `radio-play`, `radio-audio`, `radio-time`, `radio-error`.
