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
4. `cd infra/comfyui/ComfyUI && docker compose up -d --build`

API docs: http://localhost:3000/docs

## Fetch arena weights

From the repo root:

```bash
export HF_TOKEN=hf_...
cd infra/comfyui
make fetch-zimage COMFY_HOME=$HOME/ComfyUI
make fetch-krea2 COMFY_HOME=$HOME/ComfyUI
```

## Maya env

```bash
COMFYUI_API_URL=http://localhost:3000
COMFYUI_WEBHOOK_SECRET=<same base64 secret as WEBHOOK_SECRET>
MAYA_IMAGE_ROOT=./data/outputs/maya-image
MAYA_ARENA_PAIR=z-image-turbo-t2i,krea2-turbo-t2i
MAYA_ARENA_SIZE=512x512
```

See [`apps/maya-bot/README.md`](../../apps/maya-bot/README.md) for the full bot setup.
