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

After `docker compose up`, ComfyUI must see model weights in its loader dropdowns:

```bash
# Z-Image
curl -s http://127.0.0.1:8188/object_info/UNETLoader | jq '.UNETLoader.input.required.unet_name[0] | index("z_image_turbo_bf16.safetensors")'

# Krea2
curl -s http://127.0.0.1:8188/object_info/UNETLoader | jq '.UNETLoader.input.required.unet_name[0] | index("krea2_turbo_fp8_scaled.safetensors")'
# expect a number (file is listed), not null

# Krea2 also needs ComfyUI 0.26+ (native CLIPLoader type `krea2`)
curl -s http://127.0.0.1:8188/system_stats | jq '.system.comfyui_version'
curl -s http://127.0.0.1:8188/object_info/CLIPLoader \
  | jq '.CLIPLoader.input.required.type[0] | index("krea2")'
# expect a number, not null
```

**Model version requirements:**

| Model | Min ComfyUI | Notes |
|-------|-------------|-------|
| Z-Image Turbo | 0.19.3+ | Default local model |
| Krea 2 Turbo | **0.26.0+** | Requires `CLIPLoader type=krea2`; rebuild docker image after bump |

If Krea2 weights are visible but `krea2` is missing from CLIPLoader types, rebuild:

```bash
cd infra/comfyui/ComfyUI
COMFY_HOME=$HOME/ComfyUI docker compose up -d --build
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

Dashboard slash cmds use a **default local Comfy model** from Settings → Imagine (default `zit` / Z-Image Turbo). Override per request with `model=`:

```text
/imagine sunset over mountains model=krea2
/imagine cyberpunk city model=zit
```

Settings choices: `zit` (light), `krea2` (heavy, ~18 GB VRAM), `ideogram-local`. Env override: `MAYA_IMAGINE_DEFAULT_MODEL=krea2`.

Krea2-specific env (optional):

```bash
COMFYUI_GRAPH_KREA2_SUBMIT_TIMEOUT_SEC=120
COMFYUI_KREA2_MIN_VRAM_FREE=2147483648   # 2 GiB
COMFYUI_KREA2_REQUIRED_VRAM=19327352832  # 18 GiB
```

Smoke without GPU:

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

## Troubleshooting / correlation

When `/imagine` fails, the dashboard shows `corr_id` (chat turn), and on completion or error may show `trace_id` and `job_id`. Join keys:

| Key | Where |
|-----|--------|
| `corr_id` | Chat SSE, `image_jobs.metadata->>'corr_id'` |
| `trace_id` | OTEL spans, `image_jobs.metadata->>'trace_id'` |
| `job_id` | `image_jobs.id`, reply text |
| Comfy `prompt_id` | `image_jobs.provider_job_id`, span attr `comfyui.prompt_id` |

Debug API: `GET /api/imagine/jobs/{job_id}` returns prompt, timestamps, and correlation metadata.

Enable OTEL export for Jaeger/local collector:

```bash
export VA_OTEL_ENABLED=1
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
# or Settings → Platform → OTEL enabled (gateway lifespan)
./launch.sh
```

Lookup SQL:

```sql
SELECT id, provider_job_id,
       metadata->>'corr_id' AS corr_id,
       metadata->>'trace_id' AS trace_id,
       created_at, completed_at
FROM image_jobs
ORDER BY created_at DESC
LIMIT 10;
```
