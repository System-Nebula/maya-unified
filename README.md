# Maya Unified

All-in-one Maya stack: **qwen3 voice agent** + **maya-public platform gateway** + unified dashboard. One clone, one launcher, one settings file.

```
mic → Whisper → LLM (LM Studio / LiteLLM) → Qwen3-TTS → speakers
                      ↘ tools (Discord, web, memory, …)
```

**Default URL:** http://localhost:8090

---

## Repo layout

Everything ships in this repository:

```
maya-unified/
├── qwen3-voice-agent/   # STT / LLM / TTS / Discord tools
├── maya-public/         # platform APIs + voice SDK
├── apps/                # unified gateway + dashboard
├── services/            # settings, patches, hub
├── data/                # runtime state (gitignored)
├── launch.py
├── launch.bat           # Windows
└── launch.sh            # Linux / NixOS
```

Runtime data (settings, personalities, memory) lives in `data/` and is **not** committed.

Upstream history is preserved in commit messages; day-to-day work happens in this monorepo.

---

## Prerequisites

| Requirement | Notes |
|-------------|--------|
| **Python 3.11–3.12** | 3.13+ is not supported by the voice stack |
| **NVIDIA GPU + drivers** | Strongly recommended for real-time TTS/STT |
| **FFmpeg** | Required for Discord voice / YouTube playback |
| **LM Studio** (or compatible API) | OpenAI-compatible server at `http://localhost:1234/v1` |

Optional: **SoX**, **Discord bot token**, **ComfyUI** + Postgres (full `/imagine` arena via `maya-bot`).

---

## Windows installation

### 1. Clone

```powershell
git clone https://github.com/System-Nebula/maya-unified.git
cd maya-unified
```

### 2. Voice agent runtime

```bat
cd qwen3-voice-agent
setup_windows.bat
```

<details>
<summary>Manual install (if setup_windows.bat fails)</summary>

```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip wheel setuptools
pip install "torch>=2.7.0" torchaudio --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt
```

Verify: `python -c "import torch; print(torch.cuda.is_available())"` → `True`
</details>

### 3. FFmpeg

```powershell
winget install Gyan.FFmpeg
```

### 4. Unified launcher

```bat
cd ..
copy .env.example .env
qwen3-voice-agent\.venv\Scripts\pip install -e .
```

### 5. (Optional) maya-public platform extras

```bat
cd maya-public
uv sync --all-packages
cd ..
```

### 6. Configure

Edit `.env` (and/or `qwen3-voice-agent/.env`):

```env
PORT=8090
VA_LLM_BASE_URL=http://localhost:1234/v1
VA_LLM_MODEL=your-model-id-from-lm-studio
VA_LLM_API_KEY=lm-studio
```

Discord, memory, voice reference audio, etc. can also be set in **Settings** at http://localhost:8090/settings .

### 7. Start LM Studio

Load an instruct model and start the local server on port **1234**.

### 8. Launch

```bat
launch.bat
```

Or:

```bat
qwen3-voice-agent\.venv\Scripts\python.exe launch.py
```

Open http://localhost:8090 — first TTS load can take several minutes on GPU.

---

## NixOS installation

### 1. Clone

```bash
git clone https://github.com/System-Nebula/maya-unified.git
cd maya-unified
```

### 2. GPU + unfree packages

In `configuration.nix`:

```nix
{
  services.xserver.videoDrivers = [ "nvidia" ];
  hardware.nvidia.package = config.boot.kernelPackages.nvidiaPackages.stable;
  nixpkgs.config.allowUnfree = true;
}
```

`sudo nixos-rebuild switch`

### 3. Dev shell

```bash
nix develop
```

Provides FFmpeg, SoX, Python 3.11, PortAudio, and build headers.

### 4. Python venv (PyTorch via pip wheels)

```bash
cd qwen3-voice-agent
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel setuptools
pip install torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt
python -c "import torch; print('cuda:', torch.cuda.is_available())"
```

### 5. Unified launcher

```bash
cd ..
cp .env.example .env
qwen3-voice-agent/.venv/bin/pip install -e .
```

### 6. Launch

```bash
./launch.sh
```

Open http://localhost:8090

### NixOS troubleshooting

| Issue | Fix |
|-------|-----|
| PortAudio / `sounddevice` errors | Run inside `nix develop` |
| `torch.cuda.is_available()` → False | Check `nvidia-smi` and CUDA wheel variant |
| Discord YouTube age-restricted | Export `cookies.txt` → Settings → Discord → YouTube cookies file |

---

## Web UI

| URL | Purpose |
|-----|---------|
| `/` | Dashboard — EQ, chat, tools |
| `/memory` | Memory explorer |
| `/settings` | Server config (`data/settings.json`) |
| `/docs` | OpenAPI |
| `/api/voice/agent/*` | Voice session, SSE, personalities |

---

## LLM backends

| Provider | Voice pipeline |
|----------|----------------|
| **LM Studio** (default) | Yes |
| **LiteLLM** (proxy or SDK) | Yes — Settings → Reasoning |
| **WebLLM** (browser WebGPU) | Conversation text only |

---

## Discord

Set a bot token in **Settings → Discord**. The agent reloads when you save.

Voice join, YouTube play/queue, volume, and text tools are included. For age-restricted YouTube on Windows, use a **cookies file** in Settings (browser import often fails while the browser is open).

Full **`/imagine`** arena: `uv run maya-bot` from `maya-public/` with ComfyUI + Postgres.

---

## Data

| Path | Contents |
|------|----------|
| `data/settings.json` | Dashboard settings |
| `data/personalities.json` | Character cards |
| `data/memory/` | Markdown memory |
| `data/*.db` | Session / memory DBs |

On first run, legacy data from `qwen3-voice-agent/data/` is copied once into `data/` (marker: `data/.migrated-from-qwen3`).

---

## Development

Unified-only changes go in `apps/` and `services/`. Prefer patching via `services/` rather than editing bundled trees directly.

```bash
qwen3-voice-agent/.venv/bin/pip install -e .
./launch.sh
```

Standalone qwen3 WebUI (legacy): `cd qwen3-voice-agent && python server.py` → http://127.0.0.1:7861

---

## Quick checklist

1. `git clone` this repo
2. `cd qwen3-voice-agent && setup_windows.bat` (or NixOS venv steps above)
3. `pip install -e .` from repo root with the qwen3 venv
4. Copy `.env.example` → `.env`, start LM Studio
5. `launch.bat` or `./launch.sh`
