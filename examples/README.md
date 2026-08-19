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

- `dev-seed.json` — first-run OpenBao KV seed, including the bundled **maya-dev-example** slskd test account and local Postgres (`secret/maya/integrations/postgres`, matching docker-compose / GHA pgvector)

Copied once to `data/openbao/dev-seed.json` by `make openbao`. New example paths are merged into an existing seed without overwriting a throwaway Soulseek login. `make slskd` replaces slskd with a throwaway Soulseek login (created on first connect) unless `SLSKD_EXAMPLE=1`. Drop `"network": "example"` and set a real username/password to use an existing account.

## `slskd/`

- `search_responses.json` — brat + Never Gonna Give You Up 7″ FLAC fixtures served by the example slskd stand-in when the test account is active

Your own uploads, settings, and memory stay in `data/` (gitignored).
