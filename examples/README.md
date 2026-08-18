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

## `openbao/`

- `dev-seed.json` — first-run OpenBao KV seed, including the bundled **maya-dev-example** slskd test account

Copied once to `data/openbao/dev-seed.json` by `make openbao`. Replace that copy with a real Soulseek login (and drop `"network": "example"`) to use the live network.

## `slskd/`

- `search_responses.json` — brat + Never Gonna Give You Up 7″ FLAC fixtures served by the example slskd stand-in when the test account is active

Your own uploads, settings, and memory stay in `data/` (gitignored).
