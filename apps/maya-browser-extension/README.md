# Maya Browser Companion (MV3)

Chrome/Vivaldi extension that captures pages and POSTs to `POST /api/browser/capture` on the Maya unified gateway.

## Setup

1. Set `MAYA_BROWSER_CAPTURE_TOKEN` in the gateway `.env`.
2. Load unpacked: `chrome://extensions` → Developer mode → Load unpacked → select this directory.
3. Open extension **Options** — set gateway URL (default `http://localhost:8090`) and the same capture token.
4. Run the capture worker: `uv run python -m services.browser.worker` from maya-unified root.

## Usage

- **Side panel**: Save / Research / Capture screenshot
- **Context menu**: Right-click → "Save to Maya"

## Icons

Place PNG icons at `icons/icon16.png`, `icons/icon48.png`, `icons/icon128.png` (any solid-color placeholders work for dev).
