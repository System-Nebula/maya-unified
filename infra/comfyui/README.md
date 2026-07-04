# ComfyUI stack for Maya `/imagine`

Maya's Discord bot talks to **comfyui-api on port 3000** (`COMFYUI_API_URL`). This folder
ships workflow JSON, weight fetch scripts, and a scrubbed Docker Compose template.

## Prerequisites

- NVIDIA GPU + Docker with `nvidia-container-toolkit`
- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Writable ComfyUI data directory (default `~/ComfyUI`):

```bash
mkdir -p ~/ComfyUI/models ~/ComfyUI/custom_nodes ~/ComfyUI/{input,user,output}
```

## Build comfyui-api

1. Clone [SaladTechnologies/comfyui-api](https://github.com/SaladTechnologies/comfyui-api) into `infra/comfyui/ComfyUI/` (or your fork).
2. Copy `docker-compose.yml` from this repo into that directory.
3. Copy `.env.example` → `.env` and set `HF_TOKEN` + `WEBHOOK_SECRET`.
4. `cd infra/comfyui/ComfyUI && COMFY_HOME=$HOME/ComfyUI docker compose up -d --build`

Salad comfyui-api runs ComfyUI from **`/opt/ComfyUI`**. The compose file bind-mounts your host data dir there (not `/app/ComfyUI`):

```yaml
${COMFY_HOME}/models → /opt/ComfyUI/models
```

API docs: http://localhost:3030/docs (host port 3030 maps to container 3000)

### Verify models are visible to ComfyUI

After `docker compose up`, ComfyUI must see Z-Image weights in its loader dropdowns:

```bash
curl -s http://127.0.0.1:8188/object_info/VAELoader | jq '.VAELoader.input.required.vae_name[0]'
# expect ae.safetensors (not just ["pixel_space"])

curl -s http://127.0.0.1:8188/object_info/UNETLoader | jq '.UNETLoader.input.required.unet_name[0] | index("z_image_turbo_bf16.safetensors")'
# expect a number (file is listed)
```

If loaders are empty but files exist under `~/ComfyUI/models/`, the volume mount target is wrong — use `/opt/ComfyUI/models` as in this repo's `docker-compose.yml`.

### Port check (before `/imagine`)

`COMFYUI_API_URL` must reach **comfyui-api**, not another web app on port 3000 (a Next.js 404 returns HTML and breaks dashboard `/imagine`):

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:3000/docs
# expect 200 — if you see HTML or 404, stop the other process or change COMFYUI_API_URL
```

If port 3000 is taken, point Maya at the actual comfyui-api port (e.g. `http://127.0.0.1:3030`).

## Service discovery (gateway)

On startup the unified gateway probes `COMFYUI_API_URL` (or Settings → Imagine → ComfyUI URL). If that URL fails (wrong app on :3000, connection refused, HTML 404), Maya scans localhost candidate ports (`MAYA_COMFY_DISCOVERY_PORTS`, default `3000,3030`) and **auto-adopts** the first valid comfyui-api.

**Dev policy** (`ENV=development`): if no local comfyui-api responds and `MAYA_FAKE_COMFY` is unset, the gateway still starts but `capabilities.imagine` is false and `/imagine` is blocked with an actionable message. Set `MAYA_FAKE_COMFY=1` for GPU-free smoke without Comfy.

Check status: `curl http://localhost:8090/api/voice/agent/status` → `services.comfyui` and `capabilities.imagine`.

## Fetch arena weights

From the repo root:

```bash
export HF_TOKEN=hf_...
cd infra/comfyui
make fetch-zimage COMFY_HOME=$HOME/ComfyUI
make fetch-krea2 COMFY_HOME=$HOME/ComfyUI
```

## Maya env

### Dashboard chat `/imagine` (unified gateway)

Dashboard slash cmds default to **Z-Image Turbo** via Comfy (`model=zit`). Smoke without GPU:

```bash
export MAYA_FAKE_COMFY=1
./launch.sh
# conversation page → /imagine a doge shiba inu anime style
```

Real Comfy output:

```bash
unset MAYA_FAKE_COMFY
export COMFYUI_API_URL=http://127.0.0.1:3030
export MAYA_IMAGE_ROOT=./data/outputs/maya-image
# fetch weights first (see above)
./launch.sh
```

### Discord / arena

```bash
COMFYUI_API_URL=http://localhost:3000
COMFYUI_WEBHOOK_SECRET=<same base64 secret as WEBHOOK_SECRET>
MAYA_IMAGE_ROOT=./data/outputs/maya-image
MAYA_ARENA_PAIR=z-image-turbo-t2i,krea2-turbo-t2i
MAYA_ARENA_SIZE=512x512
```

See [`apps/maya-bot/README.md`](../../apps/maya-bot/README.md) for the full bot setup.
