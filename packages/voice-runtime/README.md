# Voice Agent (Qwen3)

> **This repository is the `qwen3-voice-agent` project only** — a local streaming voice assistant with Qwen3-TTS, a web control panel, SillyTavern-style character cards, layered memory, Discord tools, and optional VTuber support.

Talk into your mic → faster-whisper transcribes → an LLM in [LM Studio](https://lmstudio.ai) replies → [faster-qwen3-tts](https://github.com/andimarafioti/faster-qwen3-tts) speaks in a cloned or built-in voice. Everything runs on your machine.

```
mic → VAD → faster-whisper → LM Studio (+ tools) → sentence chunker
    → Qwen3-TTS (streaming) → live EQ → speakers
                              ↘ VTube Studio (optional)
                              ↘ Discord text / voice (optional)
```

**Web UI:** http://127.0.0.1:7861 (default)

---

## LLM assembly guide

> **For AI assistants:** follow this checklist in order. Do not skip prerequisite checks. After each step, verify the success criterion before continuing.

### Preconditions (verify first)

| Check | How |
| --- | --- |
| OS | Windows 10/11 (primary target; Linux may work but is untested here) |
| GPU | NVIDIA GPU; `nvidia-smi` prints device info |
| Python | 3.10–3.12 installed (`py -3.11 --version`). **Not** 3.13+ |
| LM Studio | Installed from https://lmstudio.ai |
| Audio | Microphone works; **headphones strongly recommended** (reduces false barge-in) |
| Repo | Cloned to a path **without spaces** if possible |

### Step 1 — Clone and install dependencies

```cmd
git clone https://github.com/jov4n/voice-agent.git
cd voice-agent
setup_windows.bat
```

**What this does:** creates `.venv`, installs CUDA PyTorch (cu128 wheels for RTX 50xx), installs `requirements.txt`, verifies GPU, pre-downloads Qwen3-TTS weights.

**Success:** script ends without error; `python -c "import torch; print(torch.cuda.is_available())"` prints `True` inside the venv.

<details>
<summary>Manual install (if setup_windows.bat fails)</summary>

```cmd
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip wheel setuptools
pip install "torch>=2.7.0" torchaudio --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt
```

Older GPUs (CUDA 12.4): `pip install torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu124`
</details>

### Step 2 — Configure environment

```cmd
copy .env.example .env
```

Edit `.env` (never commit it). Minimum for a working voice session:

```env
VA_LLM_MODEL=google/gemma-3-12b-it
VA_LLM_REASONING_EFFORT=none
```

**Optional but common:**

```env
VA_DISCORD_TOKEN=your_bot_token
VA_DISCORD_GUILD_ID=your_server_id
VA_DISCORD_AUTO_REPLY=1
VA_WEB_TOOLS_ENABLED=1
VA_LLM_ORCHESTRATOR=1
VA_OTEL_ENABLED=1
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
```

All settings are also documented in [Configuration](#configuration) below. The app loads `.env` from the repo root automatically (`config.py`).

### Step 3 — Start LM Studio

1. Open LM Studio → **Discover** → download a fast **instruct** model (Gemma 3, Qwen3 8B, Llama 3.1 8B, …).
2. **Local Server** tab → load the model → **Start Server**.
3. Confirm the API is at `http://localhost:1234/v1`.
4. Copy the **exact model id** (e.g. `google/gemma-3-12b-it`) into `VA_LLM_MODEL`.

**Gemma / reasoning models:** set `VA_LLM_REASONING_EFFORT=none` or spoken replies may be empty.

**Qwen3:** hidden thinking is disabled automatically (`VA_LLM_DISABLE_THINKING=1`).

### Step 4 — Start the voice agent server

```cmd
cd voice-agent
.venv\Scripts\activate
python server.py
```

Or with explicit env (PowerShell):

```powershell
$env:VA_LLM_MODEL="google/gemma-3-12b-it"
$env:VA_LLM_REASONING_EFFORT="none"
$env:VA_LLM_ORCHESTRATOR="1"
.\.venv\Scripts\python.exe server.py --port 7861
```

**Success:** terminal logs `open http://127.0.0.1:7861` and eventually `agent ready`. First launch loads TTS + STT (can take 1–3 minutes).

### Step 5 — First run in the web UI

1. Open **http://127.0.0.1:7861** and hard-refresh if upgrading (`Ctrl+Shift+R`).
2. Wait until the mic button is enabled (status **Idle**).
3. **Voice** page → upload a 10–20 s clean WAV or use `voices\ref.wav`.
4. **Settings** → pick or build a **personality** (see [Character cards](#character-cards-sillytavern-compatible)).
5. **Talk** page → click the **mic** to start a hands-free session.
6. Speak; the agent transcribes, thinks, and replies aloud. Click mic again to stop.

### Step 6 — Optional add-ons (only if requested)

| Feature | Extra steps |
| --- | --- |
| **Discord** | Bot token in `.env`, FFmpeg on PATH, `pip install "discord.py[voice]" yt-dlp` (in requirements already) |
| **VTube Studio** | Install VTS, enable on **Avatar** page or `VA_VTS_ENABLED=1` |
| **Observability** | `docker compose -f docker-compose.observability.yml up -d` → Jaeger UI http://localhost:16686 |
| **MCP tools** | `copy mcp_servers.json.example mcp_servers.json`, edit, restart |
| **Web search** | On by default (`VA_WEB_TOOLS_ENABLED=1`); uses `ddgs` |

### Common assembly failures

| Symptom | Fix |
| --- | --- |
| `cuda available: False` | Reinstall PyTorch with correct CUDA wheel; update NVIDIA driver |
| Empty AI replies | LM Studio not running; wrong `VA_LLM_MODEL`; Gemma needs `VA_LLM_REASONING_EFFORT=none` |
| Port 7861 in use | `python server.py --port 8000` or kill the old process |
| UI stuck Loading | Hard-refresh; check terminal for Python traceback |
| Discord tools missing | Set `VA_DISCORD_TOKEN`; restart server |

---

## Features

| Area | What you get |
| --- | --- |
| **Speech-to-text** | faster-whisper (`small.en` default), CUDA-accelerated |
| **LLM** | Any OpenAI-compatible local server (LM Studio) |
| **Orchestrator** | Routes garbled STT + context to Discord/web/tools (`VA_LLM_ORCHESTRATOR`) |
| **Text-to-speech** | Real-time streaming clone or CustomVoice speakers |
| **Latency** | Token stream → sentence chunks → audio played as generated |
| **Barge-in** | Smart (STT-based), instant (VAD), or off |
| **Web UI** | Talk, Voice, Avatar, Settings, Memory, Tools |
| **Character cards** | SillyTavern V2 JSON/PNG import, smart LLM builder, personality presets |
| **Voice clone** | Upload WAV in UI or drop `voices\ref.wav` |
| **Live EQ** | Presets + custom bands + spectrum visualizer |
| **VTuber** | Lip-sync + expressions via VTube Studio |
| **Discord** | Voice channels, YouTube queue, text post/read/reply, @mention auto-reply |
| **Web tools** | DuckDuckGo search + weather (no API key for weather) |
| **Tools** | Memory, session search, skills, MCP servers |
| **Memory** | Curated notes, session DB, semantic recall, scoped user/guild memory |
| **Observability** | OpenTelemetry traces/metrics/logs → Jaeger (optional) |

---

## Quick start (human)

Same as the LLM guide, condensed:

```cmd
git clone https://github.com/jov4n/voice-agent.git
cd voice-agent
setup_windows.bat
copy .env.example .env
REM edit .env — set VA_LLM_MODEL to your LM Studio model id
REM start LM Studio local server on :1234
.venv\Scripts\activate
python server.py
```

Open http://127.0.0.1:7861 → wait for **Idle** → mic on → talk.

---

## Web UI overview

| Page | Purpose |
| --- | --- |
| **Talk** | Mic session, live transcript, output EQ + spectrum |
| **Voice** | Clone voices (upload/select), preview, voice description |
| **Avatar** | VTube Studio connection, expression mapping |
| **Settings** | Personalities / character cards, delivery, barge-in, volumes |
| **Memory** | Edit MEMORY.md & USER.md, approve staged writes, explore DBs, skills |
| **Tools** | Live tool-call log (Discord, web, memory, MCP) |

### Character cards (SillyTavern-compatible)

Under **Settings → Personality**:

- **Saved personalities** — switch presets without losing card data.
- **Smart builder** — describe a character in plain language; the LLM fills V2 card fields.
- **Import card** — `.json` (Character Card V2) or SillyTavern `.png` (embedded `chara` / `ccv3` chunk).
- **Export card** — download JSON.
- **Card fields** — description, personality, scenario, first message, example dialogue, system prompt override, post-history instructions, tags.

**How cards become speech:**

1. Card fields compile into a system prompt (`memory/character_card.py`).
2. `{{char}}` → character name; `{{user}}` → name parsed from `data/memory/USER.md` (e.g. “claims to be Miles”).
3. `first_mes` is spoken when you start a mic session with empty history (or switch personality mid-session).
4. `post_history_instructions` is injected after chat history on voice turns and Discord text compose.
5. `creator_notes` and `tags` are **not** sent to the model.

Example `USER.md` entry for name substitution:

```markdown
The user claims to be Alex, a game developer.
```

---

## Command-line modes

No browser:

```cmd
.venv\Scripts\activate
python app.py --mode typed          :: type text, hear reply
python app.py --mode ptt --seconds 5 :: push-to-talk
python app.py --mode vad            :: hands-free + barge-in
python app.py --list-speakers       :: CustomVoice speaker IDs
```

Quit typed/ptt with `q`. Quit VAD with `Ctrl+C`.

---

## Voice cloning

**Default:** clone mode with x-vector-only (`VA_TTS_XVEC_ONLY=1`) — timbre from embedding, not replaying the reference clip.

| Method | How |
| --- | --- |
| Web UI | **Voice** page → upload WAV/FLAC/MP3/OGG/M4A |
| File drop | `voices\ref.wav` before launch |
| Library | Files in `voices\` appear in the dropdown |

**Tips:** one speaker, 10–20 s, clean audio, normal pace, ends on silence.

**ICL mode** (max likeness, needs transcript): `VA_TTS_XVEC_ONLY=0` + `voices\ref.txt` with exact spoken words.

**Built-in speakers** (no reference clip):

```cmd
set VA_TTS_MODE=custom
set VA_TTS_SPEAKER=aiden
```

---

## Tools, MCP, memory & Discord

### Turn pipeline

```
speech → STT → [orchestrator] → memory prefetch → LLM ⇄ tools (≤3 rounds) → spoken reply
                                                          ↓
                                            session log → background review → memory/skills
```

### Tool modes

`VA_TOOL_MODE=auto|native|json` — `auto` tries OpenAI function calling, falls back to JSON tool blocks (needed for Gemma).

### MCP

1. `pip install mcp` (in requirements)
2. `copy mcp_servers.json.example mcp_servers.json`
3. Enable servers, restart agent. Tools are namespaced (`filesystem__read_file`, …).

### Discord

1. [Discord Developer Portal](https://discord.com/developers/applications) → bot token.
2. Invite with **Connect**, **Speak**, **Send Messages**, **Read Message History**.
3. FFmpeg on PATH.
4. In `.env`:

```env
VA_DISCORD_TOKEN=...
VA_DISCORD_GUILD_ID=...
VA_DISCORD_AUTO_REPLY=1
```

Voice examples: *“Join Music”*, *“Play lofi on YouTube”*. Text: *“Post hello in general”*, *“Read the last messages in dev-chat”*. @mentions and replies can auto-compose a text response using the active personality.

### Memory layers

| Layer | Storage | Use |
| --- | --- | --- |
| **Curated** | `data/memory/MEMORY.md`, `USER.md` | Frozen into prompt; editable on **Memory** page |
| **Scoped** | `data/memory/users/`, `guilds/` | Per-Discord-user / per-server notes |
| **Sessions** | `data/state.db` | FTS search + Memory explorer |
| **Cognitive** | `data/cognitive.db` | Semantic prefetch (`fastembed`) |
| **Skills** | `data/skills/` | Procedural notes via `skill` tool |
| **Personalities** | `data/personalities.json` | Character card presets |

Post-turn **review** extracts durable facts. With `VA_MEMORY_WRITE_APPROVAL=1`, writes wait for UI approval. All of `data/` is gitignored.

---

## Observability (optional)

```cmd
docker compose -f docker-compose.observability.yml up -d
```

| Service | URL |
| --- | --- |
| Jaeger UI | http://localhost:16686 |
| OTLP gRPC | http://localhost:4317 |

Enable in `.env`: `VA_OTEL_ENABLED=1`, `VA_LOG_FORMAT=json` (optional structured logs).

---

## VTube Studio (optional)

1. Run [VTube Studio](https://denchisoft.com/).
2. **Avatar** page → enable VTuber (`VA_VTS_ENABLED=1`).
3. Approve plugin on first connect → `vts_token.json` saved (gitignored).
4. **Auto expressions** maps emotion cues to hotkeys; independent from voice delivery cues.

---

## Configuration

Settings live in [`config.py`](config.py) and override via environment variables or `.env`.

### Essential

| Variable | Default | Purpose |
| --- | --- | --- |
| `VA_LLM_BASE_URL` | `http://localhost:1234/v1` | LM Studio / OpenAI-compatible endpoint |
| `VA_LLM_MODEL` | `local-model` | **Must match** loaded model id |
| `VA_LLM_MAX_TOKENS` | `220` | Shorter = snappier speech |
| `VA_LLM_REASONING_EFFORT` | *(empty)* | `none` for Gemma-style models |
| `VA_LLM_ORCHESTRATOR` | `1` | STT intent routing |
| `VA_TTS_MODE` | `clone` | `clone` or `custom` |
| `VA_TTS_DELIVERY` | `full` | `full` / `hybrid` / `off` |
| `VA_BARGE_MODE` | `smart` | `smart` / `instant` / `off` |
| `VA_DATA_DIR` | `data` | Personalities, memory, DBs |

### Discord

| Variable | Default | Purpose |
| --- | --- | --- |
| `VA_DISCORD_ENABLED` | on if token set | Register Discord tools |
| `VA_DISCORD_TOKEN` | *(empty)* | Bot token |
| `VA_DISCORD_GUILD_ID` | `0` | Default server id |
| `VA_DISCORD_AUTO_REPLY` | `1` | Reply on @mention / thread reply |
| `VA_DISCORD_MUSIC_VOLUME` | `0.85` | YouTube playback volume |

### Memory

| Variable | Default | Purpose |
| --- | --- | --- |
| `VA_MEMORY_ENABLED` | `1` | Memory stack |
| `VA_MEMORY_WRITE_APPROVAL` | `0` | Stage writes for UI approval |
| `VA_COGNITIVE_MEMORY` | `1` | Semantic recall |
| `VA_REVIEW_ENABLED` | `1` | Post-turn adaptation |

### Observability

| Variable | Default | Purpose |
| --- | --- | --- |
| `VA_OTEL_ENABLED` | `0` | Export traces/metrics/logs |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | Collector address |
| `VA_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, … |
| `VA_LOG_FORMAT` | `text` | `text` or `json` |

See `config.py` and `.env.example` for the full list (TTS, EQ, VTS, MCP, web tools, …).

### Example launch (Gemma + Discord + orchestrator)

```powershell
.venv\Scripts\activate
$env:VA_LLM_MODEL="google/gemma-3-12b-it"
$env:VA_LLM_REASONING_EFFORT="none"
$env:VA_LLM_ORCHESTRATOR="1"
$env:VA_DISCORD_TOKEN="your_token"
python server.py
```

---

## Latency tuning

- **TTS model:** `Qwen3-TTS-12Hz-0.6B-Base` (default) = fastest time-to-first-audio.
- **Chunk size:** `VA_TTS_CHUNK_SIZE=4` — try `8` if GPU is saturated.
- **Delivery:** `full` = most natural; `hybrid` = first sentence fast; `off` = per-sentence.
- **LLM:** 7B–14B instruct models; keep `max_tokens` low; character cards include voice-length rules.
- **STT:** `small.en` balances speed and accuracy.

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `torch.cuda.is_available()` is False | Reinstall PyTorch CUDA wheel (`cu128` for RTX 50xx) |
| Empty / no spoken reply | LM Studio running? Correct `VA_LLM_MODEL`? Gemma: `VA_LLM_REASONING_EFFORT=none` |
| Reference audio plays at start | Keep `VA_TTS_XVEC_ONLY=1` |
| Inconsistent tone across sentences | `VA_TTS_DELIVERY=full` |
| False barge-ins | Headphones; `VA_BARGE_MODE=smart`; or `VA_BARGE_IN=0` |
| Port in use | `python server.py --port 8000` |
| Personality import fails | JSON must be V2 (`spec: chara_card_v2`); PNG must be SillyTavern card image |
| `{{user}}` shows “the user” | Add name to `data/memory/USER.md`; re-activate personality |
| No opening greeting | Card needs `first_mes`; start mic with empty history |
| VTS won't connect | VTube Studio running; approve plugin prompt |

---

## Project layout

All paths are relative to the **repo root** (clone = project root, no extra subfolder):

```
├── server.py                 # Web UI entry (FastAPI + SSE) — use this
├── app.py                    # CLI entry (typed / ptt / vad)
├── agent.py                  # Turn loop, personalities, barge-in, Discord compose
├── config.py                 # Settings (env + .env)
├── llm.py                    # OpenAI-compatible streaming client
├── observability.py          # OpenTelemetry setup
├── docker-compose.observability.yml
├── .env.example              # Copy to .env
├── setup_windows.bat         # Windows one-shot installer
├── tools/                    # Tool registry, loop, Discord, web, MCP
├── memory/
│   ├── character_card.py     # SillyTavern V2 compile/import/export
│   ├── character_builder.py  # LLM smart card builder
│   ├── png_card.py           # SillyTavern PNG import
│   ├── personalities.py      # Preset store (data/personalities.json)
│   ├── user_profile.py       # USER.md → {{user}} name
│   ├── manager.py            # Memory orchestrator
│   ├── curated.py            # MEMORY.md / USER.md
│   ├── sessions.py           # SQLite + FTS5
│   ├── cognitive.py          # Embeddings recall
│   ├── skills.py             # Procedural memory
│   └── review.py             # Post-turn adaptation
├── static/index.html         # Web dashboard
├── voices/                   # Reference clips (add your own)
└── data/                     # Runtime state (gitignored)
    ├── personalities.json
    ├── settings.json
    └── memory/
        ├── MEMORY.md
        └── USER.md
```

### HTTP API (for automation)

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/` | GET | Web UI |
| `/config` | GET/POST | Read/update runtime settings |
| `/personalities` | GET | List active personality + card |
| `/personalities/save` | POST | Save/update preset |
| `/personalities/import` | POST | Import V2 JSON |
| `/personalities/import-png` | POST | Import SillyTavern PNG |
| `/personalities/build` | POST | Smart builder (`{"prompt":"..."}`) |
| `/start` / `/stop` | POST | Mic session |
| `/events` | GET | SSE event stream |
| `/memory` | GET | Memory status |
| `/memory-explore` | GET | Browse state/cognitive DBs |

---

## License & credits

- TTS: [faster-qwen3-tts](https://github.com/andimarafioti/faster-qwen3-tts) / Qwen3-TTS
- STT: [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- Character cards: [Character Card V2 spec](https://github.com/bradennapier/character-cards-v2)
- LLM: any model you load in LM Studio

Voice reference clips are **not** included — add your own under `voices/`.
