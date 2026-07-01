# Maya Unified

Single launcher for the **Maya voice agent** ([qwen3-voice-agent](https://github.com/jov4n/voice-agent)) and **Maya platform gateway** ([maya-public](https://github.com/System-Nebula/maya-public)) — one web UI, one settings file, one process.

```
mic → Whisper → LLM (LM Studio / LiteLLM) → Qwen3-TTS → speakers
                      ↘ tools (Discord, web, memory, …)
```

**Default URL:** http://localhost:8090

---

## What this repo is

`maya-unified` is the **glue layer** only. It does not vendor the voice engine or platform SDK — those live in sibling folders:

```
voice-agent/                 # your workspace root (any name)
├── qwen3-voice-agent/       # STT / LLM / TTS / Discord tools (read-only upstream)
├── maya-public/             # platform APIs + voice SDK (read-only upstream)
└── maya-unified/              # ← this repo — launcher + dashboard + patches
```

On first run, agent data (settings, personalities, memory) is stored under `maya-unified/data/` and is **not** committed to git.

---

## Prerequisites (all platforms)

| Requirement | Notes |
|-------------|--------|
| **Python 3.11–3.12** | 3.13+ is not supported by the voice stack |
| **NVIDIA GPU + drivers** | Strongly recommended for real-time TTS/STT |
| **FFmpeg** | Required for Discord voice / YouTube playback |
| **LM Studio** (or compatible API) | OpenAI-compatible server at `http://localhost:1234/v1` |
| **Sibling repos** | Clone `qwen3-voice-agent` and `maya-public` next to this folder |

Optional: **SoX** (audio utilities — some TTS paths warn if missing), **Discord bot token** (voice/music tools), **ComfyUI** (full `/imagine` arena via `maya-bot`).

---

## Windows installation

### 1. Clone the workspace

```powershell
mkdir voice-agent
cd voice-agent

git clone https://github.com/jov4n/voice-agent.git qwen3-voice-agent
git clone https://github.com/System-Nebula/maya-public.git maya-public
git clone https://github.com/System-Nebula/maya-unified.git maya-unified
```

### 2. Install the voice agent runtime

Use the qwen3 Windows setup script (creates `.venv`, installs CUDA PyTorch, downloads TTS weights):

```bat
cd qwen3-voice-agent
setup_windows.bat
```

<details>
<summary>Manual Windows install (if the script fails)</summary>

```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip wheel setuptools

REM RTX 50xx / CUDA 12.8:
pip install "torch>=2.7.0" torchaudio --index-url https://download.pytorch.org/whl/cu128

REM Older CUDA 12.4:
REM pip install torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu124

pip install -r requirements.txt
```

Verify GPU: `python -c "import torch; print(torch.cuda.is_available())"` → `True`
</details>

### 3. Install FFmpeg

```powershell
winget install Gyan.FFmpeg
```

Or add FFmpeg to `PATH` any other way. Discord YouTube playback will not work without it.

### 4. Install Maya Unified

```bat
cd ..\maya-unified
copy .env.example .env
..\qwen3-voice-agent\.venv\Scripts\pip install -e .
```

### 5. (Optional) maya-public platform APIs

Only needed for arena, discover, Postgres-backed features:

```bat
cd ..\maya-public
uv sync --all-packages
```

### 6. Configure environment

Edit `maya-unified/.env` (and/or `qwen3-voice-agent/.env`):

```env
PORT=8090
VA_LLM_BASE_URL=http://localhost:1234/v1
VA_LLM_MODEL=your-model-id-from-lm-studio
VA_LLM_API_KEY=lm-studio
```

Discord (optional):

```env
VA_DISCORD_ENABLED=1
VA_DISCORD_TOKEN=your_bot_token
VA_DISCORD_GUILD_ID=your_server_id
```

Most options can also be changed in the web UI under **Settings**.

### 7. Start LM Studio

1. Download and load an instruct model.
2. Start the local server on port **1234**.
3. Copy the exact model id into Settings → Reasoning (or `.env`).

### 8. Launch

**Recommended:**

```bat
maya-unified\launch.bat
```

Or explicitly:

```bat
qwen3-voice-agent\.venv\Scripts\python.exe maya-unified\launch.py
```

Open http://localhost:8090 — first TTS model load can take several minutes on GPU.

---

## NixOS installation

NixOS is supported via a **dev shell** (system libraries) plus a **Python venv** for PyTorch/CUDA wheels that are not fully packaged in nixpkgs.

### 1. Clone the workspace

```bash
mkdir -p ~/voice-agent && cd ~/voice-agent

git clone https://github.com/jov4n/voice-agent.git qwen3-voice-agent
git clone https://github.com/System-Nebula/maya-public.git maya-public
git clone https://github.com/System-Nebula/maya-unified.git maya-unified
```

### 2. Enable GPU + unfree packages

In `configuration.nix` (or Home Manager):

```nix
{
  # NVIDIA — adjust for your hardware
  services.xserver.videoDrivers = [ "nvidia" ];
  hardware.nvidia.package = config.boot.kernelPackages.nvidiaPackages.stable;

  nixpkgs.config.allowUnfree = true;
}
```

Rebuild: `sudo nixos-rebuild switch`

### 3. Enter the dev shell

From `maya-unified/`:

```bash
nix develop
```

This provides FFmpeg, SoX, Python 3.11, PortAudio, and common build headers. CUDA still comes from pip wheels inside the venv (see next step).

### 4. Create the Python environment

```bash
cd ../qwen3-voice-agent
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel setuptools

# Pick the PyTorch index that matches your driver/CUDA — example for CUDA 12.4:
pip install torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt

python -c "import torch; print('cuda:', torch.cuda.is_available())"
```

### 5. Install Maya Unified

```bash
cd ../maya-unified
cp .env.example .env
../qwen3-voice-agent/.venv/bin/pip install -e .
```

### 6. (Optional) maya-public

```bash
cd ../maya-public
nix develop   # if maya-public provides a flake; otherwise use uv
uv sync --all-packages
```

### 7. Launch

```bash
cd ../maya-unified
./launch.sh
# or:
../qwen3-voice-agent/.venv/bin/python launch.py
```

Open http://localhost:8090

### NixOS troubleshooting

| Issue | Fix |
|-------|-----|
| `sounddevice` / PortAudio errors | Stay inside `nix develop` so `portaudio` is on `LD_LIBRARY_PATH` |
| `torch.cuda.is_available()` → False | Check `nvidia-smi`, driver module, and that you installed the matching cu124/cu128 wheel |
| SoX warning on TTS load | Harmless for basic use; dev shell includes `sox` |
| Discord YouTube age-restricted | Export `cookies.txt` → Settings → Discord → YouTube cookies file |

---

## Web UI

| URL | Purpose |
|-----|---------|
| `/` | Dashboard — EQ, chat, tools sidebar |
| `/memory` | Memory explorer |
| `/settings` | Server-persisted config (`data/settings.json`) |
| `/docs` | OpenAPI |
| `/api/voice/agent/*` | Voice session, SSE events, personalities |
| `/api/voice/settings` | Unified settings GET/POST |

Navigation: **Dashboard** · **Memory** · **Settings** · **API**

---

## LLM backends

| Provider | Where | Voice pipeline |
|----------|-------|----------------|
| **LM Studio** (default) | Local server | Yes |
| **LiteLLM** | Server proxy or SDK | Yes — Settings → Reasoning |
| **WebLLM** | Browser (WebGPU) | Conversation text only |

**LiteLLM proxy example:** `litellm --model ollama/llama3` on `:4000`, then set base URL `http://localhost:4000/v1` in Settings.

---

## Discord

When a bot token is saved in Settings → Discord, qwen3 `DiscordManager` loads automatically (agent reloads on save).

Features: join voice, play/queue YouTube, volume, text read/reply.

**YouTube on Windows:** if playback fails on age-restricted videos, export a `cookies.txt` from a logged-in YouTube session and set **YouTube cookies file** in Settings (browser cookie import often fails while the browser is open).

**Default voice channel:** set in Settings so the bot auto-joins before playing music.

Full **`/imagine`** arena (ComfyUI + Postgres): run `uv run maya-bot` from `maya-public` alongside this launcher.

---

## Data & migration

| Path | Contents |
|------|----------|
| `data/settings.json` | All dashboard settings |
| `data/personalities.json` | Character cards |
| `data/memory/` | Markdown memory files |
| `data/*.db` | Memory / session databases |

On first run, existing qwen3 data under `qwen3-voice-agent/` is **copied once** into `maya-unified/data/` (marker: `data/.migrated-from-qwen3`). Your qwen3 tree is never modified.

`examples/personalities/maya-default.json` seeds personalities if the file is empty.

---

## Development

```bash
# From maya-unified/ with qwen3 venv active
pip install -e .
python launch.py
```

**Do not edit** `qwen3-voice-agent/` or `maya-public/` for unified features — add patches under `maya-unified/services/`.

---

## Friend setup checklist

1. Clone all three sibling repos (same parent folder).
2. Install qwen3 deps + GPU PyTorch (Windows: `setup_windows.bat`; NixOS: `nix develop` + venv).
3. `pip install -e .` in `maya-unified` using the **qwen3 venv**.
4. Copy `.env.example` → `.env`, start LM Studio.
5. `launch.bat` (Windows) or `./launch.sh` (Linux/NixOS).
6. Open `/settings` for LLM URL, Discord, voice reference audio.

---

## License

See upstream repos for qwen3-voice-agent and maya-public licensing. This launcher layer follows the same workspace terms.
