# Examples

Shipped assets copied into your local runtime on **first launch** (skipped if you already have data).

## `voices/`

- `ref.wav` — default clone reference (~10s)
- `ref.txt` — transcript for ICL mode

Copied to `packages/voice-runtime/voices/`.

## `personalities/`

- `personalities.json` — Maya-sama (active), Professor Mari, Call Center Scammer
- `maya-default.json` — minimal fallback if the bundle is missing

Copied to `data/personalities.json` when that file is empty.

## `skills/`

- `voice-clone.md` — quick notes on reference clips and ICL vs x-vector mode

Copied to `data/skills/` when each file is missing.

Your own uploads, settings, and memory stay in `data/` (gitignored).
