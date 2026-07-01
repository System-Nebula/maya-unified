# Contributing to Maya Unified

This repo is the **distribution/launcher wrapper**: the launcher, unified
gateway/dashboard glue in `apps/` and `services/`, and install docs live here.

The platform itself does **not** live here:

| Directory | Canonical home | How to change it |
|-----------|----------------|------------------|
| `maya-public/` | [System-Nebula/maya-public](https://github.com/System-Nebula/maya-public) | Branch + PR there, then `scripts/sync-maya-public.sh` here |
| `qwen3-voice-agent/` | [jov4n/voice-agent](https://github.com/jov4n/voice-agent) | PR there, re-vendor here |

## Ground rules

1. **One canonical repo per component — branches, not new repos.** If a build
   feels tangled, cut a branch in the canonical repo and PR it. Spinning up a
   fresh repo forks history and strands everyone else's work.
2. Never edit files under `maya-public/` in this repo; the next subtree sync
   will clobber them. Upstream the change instead.
3. Launcher/glue changes (`launch.py`, `apps/`, `services/`) are owned here —
   PR against this repo directly.
4. Follow maya-public's `docs/public-boundary.md` for anything user-visible:
   no credentials, model weights, generated media, or private service URLs.

## Syncing the platform

```bash
./scripts/sync-maya-public.sh          # pulls maya-public main into the subtree
MAYA_PUBLIC_BRANCH=some-branch ./scripts/sync-maya-public.sh   # test a branch
```
