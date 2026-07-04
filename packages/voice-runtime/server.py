"""Web control panel for the Qwen3 streaming voice agent.

Serves a single page with a big "Start talking" button. Mic capture, VAD, barge-in, and playback all run server-side in the existing pipeline (this is a
local single-machine agent); the browser is a control panel + live transcript.

Events are pushed to the browser via Server-Sent Events (SSE) so no extra
WebSocket dependency is needed.

Run:
    python server.py            # then open http://localhost:7861
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
from contextlib import asynccontextmanager
from typing import Set

# Make console output robust to characters the Windows code page can't encode
# (e.g. emoji), so a stray character never crashes the agent loop.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from observability import get_logger, setup_observability

setup_observability()
log = get_logger("server")

from fastapi import Body, FastAPI, File, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")
VOICES_DIR = os.path.join(HERE, "voices")


class Hub:
    """Owns the single VoiceAgent and fans events out to SSE subscribers."""

    def __init__(self) -> None:
        self._subscribers: Set["queue.Queue[dict]"] = set()
        self._lock = threading.Lock()
        self.agent = None
        self.ready = False
        self.status = "loading"
        self.current_voice: str | None = None

    # ----- pub/sub ----------------------------------------------------------

    def subscribe(self) -> "queue.Queue[dict]":
        q: "queue.Queue[dict]" = queue.Queue()
        with self._lock:
            self._subscribers.add(q)
        # Send a snapshot so a freshly-connected page is in sync.
        q.put({"type": "status", "value": self.status})
        q.put({"type": "ready", "value": self.ready})
        return q

    def unsubscribe(self, q: "queue.Queue[dict]") -> None:
        with self._lock:
            self._subscribers.discard(q)

    def broadcast(self, event: dict) -> None:
        if event.get("type") == "status":
            self.status = event.get("value", self.status)
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            q.put(event)

    # ----- model lifecycle --------------------------------------------------

    def load_agent(self) -> None:
        """Load models in the background so the page is responsive immediately."""
        try:
            from agent import VoiceAgent

            self.broadcast({"type": "status", "value": "loading"})
            # mode="vad" loads STT in the constructor and warms up the TTS model
            # (CUDA-graph capture), so the first click is instant.
            agent = VoiceAgent(mode="vad", on_event=self.broadcast)
            self.agent = agent
            from config import CONFIG

            self.current_voice = os.path.basename(CONFIG.tts.ref_audio)
            self.ready = True
            self.broadcast({"type": "ready", "value": True})
            self.broadcast({"type": "status", "value": "idle"})
            log.info("agent ready")
        except Exception as exc:  # noqa: BLE001
            self.ready = False
            self.broadcast({"type": "error", "text": f"Failed to load agent: {exc}"})
            self.broadcast({"type": "status", "value": "error"})
            log.exception("agent load failed")

    def get_config(self) -> dict:
        from config import CONFIG
        from eq import export_eq_catalog, list_eq_presets

        catalog = export_eq_catalog()
        bands = []
        if self.agent is not None:
            bands = self.agent.playback.eq_status().get("bands", [])
        elif CONFIG.audio.eq_preset:
            from eq import get_preset_bands
            bands = get_preset_bands(CONFIG.audio.eq_preset)

        voice = self.agent.voice if self.agent is not None else None
        loaded_tts_model = str(getattr(voice, "model_id", "") or "") if voice else ""

        return {
            "ok": True,
            "ready": self.ready,
            "system_prompt": CONFIG.llm.system_prompt,
            "personalities": self._list_personalities(),
            "delivery": CONFIG.tts.delivery,
            "tts_mode": CONFIG.tts.mode,
            "clone_model": CONFIG.tts.clone_model,
            "custom_model": CONFIG.tts.custom_model,
            "loaded_tts_model": loaded_tts_model,
            "barge_mode": (self.agent.barge_mode if self.agent is not None else CONFIG.audio.barge_mode),
            "instruct": CONFIG.tts.instruct,
            "auto_instruct": CONFIG.tts.auto_instruct,
            "auto_express": CONFIG.vts.expressions,
            "xvec_only": CONFIG.tts.xvec_only,
            "vts_enabled": CONFIG.vts.enabled,
            "eq_enabled": CONFIG.audio.eq_enabled,
            "eq_preset": CONFIG.audio.eq_preset,
            "eq_presets": list_eq_presets(),
            "eq_catalog": catalog,
            "eq_bands": bands,
            "memory_enabled": CONFIG.memory.enabled,
            "memory_write_approval": CONFIG.memory.write_approval,
            "tools_enabled": CONFIG.tools.enabled,
            "output_volume": CONFIG.audio.output_volume,
            "output_volume_percent": int(round(CONFIG.audio.output_volume * 100)),
            "output_sink": CONFIG.audio.output_sink,
            "discord_music_volume": CONFIG.discord.music_volume,
            "discord_music_volume_percent": int(round(CONFIG.discord.music_volume * 100)),
            "web_tools_enabled": CONFIG.web.enabled,
            "log_level": CONFIG.observability.log_level,
            "log_format": CONFIG.observability.log_format,
            "otel_enabled": CONFIG.observability.enabled,
        }

    def set_config(self, data: dict) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": False, "error": "agent not ready"}
        if "system_prompt" in data and isinstance(data["system_prompt"], str):
            sp = data["system_prompt"].strip()
            if sp:
                self.agent.set_system_prompt(sp)
        if "delivery" in data and isinstance(data["delivery"], str):
            self.agent.set_delivery(data["delivery"])
        if "barge_mode" in data and isinstance(data["barge_mode"], str):
            self.agent.set_barge_mode(data["barge_mode"])
        if "instruct" in data and isinstance(data["instruct"], str):
            self.agent.set_instruct(data["instruct"])
        if "auto_instruct" in data:
            self.agent.set_auto_instruct(bool(data["auto_instruct"]))
        if "auto_express" in data:
            self.agent.set_auto_express(bool(data["auto_express"]))
        if "xvec_only" in data:
            self.agent.set_xvec_only(bool(data["xvec_only"]))
        if "vts_enabled" in data:
            self.agent.set_vts_enabled(bool(data["vts_enabled"]))
        if "eq_enabled" in data:
            self.agent.set_eq_enabled(bool(data["eq_enabled"]))
        if "eq_preset" in data and isinstance(data["eq_preset"], str):
            self.agent.set_eq_preset(data["eq_preset"])
        if "eq_bands" in data and isinstance(data["eq_bands"], list):
            self.agent.set_eq_custom_bands(data["eq_bands"])
        if "memory_write_approval" in data:
            self.agent.set_write_approval(bool(data["memory_write_approval"]))
        if "output_volume" in data:
            self.agent.set_output_volume(float(data["output_volume"]))
        if "output_sink" in data and isinstance(data["output_sink"], str):
            self.agent.set_output_sink(data["output_sink"])
        if "discord_music_volume" in data:
            self.agent.set_discord_music_volume(float(data["discord_music_volume"]))
        return self.get_config()

    @staticmethod
    def _list_personalities() -> dict:
        try:
            from config import CONFIG
            from memory.personalities import PersonalityStore

            return PersonalityStore(CONFIG.memory.resolve_data_dir()).list()
        except Exception:  # noqa: BLE001
            return {"active": "", "personalities": []}

    def list_personalities(self) -> dict:
        if not self.ready or self.agent is None:
            from config import CONFIG
            from memory.personalities import PersonalityStore

            store = PersonalityStore(CONFIG.memory.resolve_data_dir())
            listing = store.list()
            active = listing.get("active") or ""
            detail = store.get(active) if active else None
            return {
                "ok": True,
                **listing,
                "card": (detail or {}).get("card"),
                "creator_notes": (detail or {}).get("creator_notes", ""),
                "post_history": (detail or {}).get("post_history", ""),
                "system_prompt": (detail or {}).get("prompt", ""),
            }
        return self.agent.list_personalities()

    def activate_personality(self, personality_id: str) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": False, "error": "agent not ready"}
        return self.agent.activate_personality(personality_id)

    def save_personality(self, data: dict) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": False, "error": "agent not ready"}
        card = data.get("card")
        return self.agent.save_personality(
            str(data.get("name", "")),
            str(data.get("prompt", "")),
            str(data.get("id", "")),
            card=card if isinstance(card, dict) else None,
            activate=bool(data.get("activate", True)),
        )

    def import_personality(self, data: dict) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": False, "error": "agent not ready"}
        return self.agent.import_personality(data, activate=bool(data.get("activate", True)))

    def import_personality_png(self, png_bytes: bytes) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": False, "error": "agent not ready"}
        return self.agent.import_personality_png(png_bytes)

    def build_character_card(self, prompt: str) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": False, "error": "agent not ready"}
        return self.agent.build_character_card(prompt)

    def export_personality(self, personality_id: str) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": False, "error": "agent not ready"}
        return self.agent.export_personality(personality_id)

    def delete_personality(self, personality_id: str) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": False, "error": "agent not ready"}
        return self.agent.delete_personality(personality_id)

    def memory_status(self) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": True, "enabled": False}
        return {"ok": True, **self.agent.memory_status()}

    def memory_approve(self, sid: str) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": False, "error": "agent not ready"}
        return self.agent.approve_memory(sid)

    def memory_reject(self, sid: str) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": False, "error": "agent not ready"}
        return self.agent.reject_memory(sid)

    def memory_edit(self, data: dict) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": False, "error": "agent not ready"}
        return self.agent.edit_memory(
            action=str(data.get("action", "")),
            target=str(data.get("target", "memory")),
            content=str(data.get("content", "")),
            old_text=str(data.get("old_text", "")),
        )

    def session_search(self, query: str) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": True, "results": []}
        return {"ok": True, "results": self.agent.session_search(query)}

    def memory_explore(
        self,
        db: str,
        limit: int = 50,
        offset: int = 0,
        session_id: str = "",
        scope: str = "",
    ) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": False, "error": "agent not ready"}
        return self.agent.memory_explore(db, limit, offset, session_id, scope)

    def read_skill(self, name: str) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": False, "error": "agent not ready"}
        return self.agent.read_skill(name)

    def tools_status(self) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": True, "enabled": False, "tools": [], "mcp": {"servers": {}}}
        return {"ok": True, **self.agent.tools_status()}

    def vts_status(self) -> dict:
        if not self.ready or self.agent is None:
            from config import CONFIG

            return {"ok": True, "enabled": CONFIG.vts.enabled, "connected": False,
                    "authenticated": False, "hotkeys": [], "expressions": [],
                    "actions": [], "emotions": [], "emotions_list": [],
                    "map": {}, "last_expression": None}
        return {"ok": True, **self.agent.vts_status()}

    def set_vts_map(self, mapping: dict) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": False, "error": "agent not ready"}
        return {"ok": True, **self.agent.set_vts_map(mapping)}

    def test_vts_action(self, name: str) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": False, "error": "agent not ready"}
        fired = self.agent.test_vts_action(name)
        return {"ok": bool(fired), "action": name}

    def start(self) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": False, "error": "agent not ready"}
        self.agent.start_session()
        return {"ok": True}

    def stop(self) -> dict:
        if self.agent is not None:
            self.agent.stop_session()
        return {"ok": True}

    def set_voice(self, path: str, *, warm: bool = True) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": False, "error": "agent not ready"}
        voice = self.agent.voice
        if not getattr(voice, "clone_capable", False):
            return {"ok": False, "error": "Server is in custom mode; restart in clone mode to upload a voice."}

        # Stop any active conversation so the new voice warmup doesn't collide.
        was_running = self.agent.is_session_running()
        self.agent.stop_session()

        # Transcript is only needed for ICL mode; skip it in x-vector mode for speed.
        # When it IS needed, ensure_ref_text auto-transcribes and caches a sidecar.
        ref_text = ""
        from config import CONFIG

        if not CONFIG.tts.xvec_only:
            ref_text = self.agent.ensure_ref_text(path)

        self.broadcast({"type": "status", "value": "loading"})
        try:
            voice.set_reference(path, ref_text=ref_text, warm=warm)
        except Exception as exc:  # noqa: BLE001
            self.broadcast({"type": "status", "value": "idle"})
            return {"ok": False, "error": str(exc)}

        self.current_voice = os.path.basename(path)
        self.broadcast({"type": "status", "value": "idle"})
        self.broadcast({"type": "voice", "name": self.current_voice})
        if was_running:
            self.agent.start_session()
        return {"ok": True, "name": self.current_voice, "file": self.current_voice}


AUDIO_EXTS = {".wav", ".flac", ".ogg", ".mp3", ".m4a", ".webm"}


def _list_voices() -> list[dict]:
    """Audio files in the voices folder; the filename (sans extension) is the name."""
    if not os.path.isdir(VOICES_DIR):
        return []
    items = []
    for fname in os.listdir(VOICES_DIR):
        if os.path.splitext(fname)[1].lower() in AUDIO_EXTS:
            items.append({"name": os.path.splitext(fname)[0], "file": fname})
    items.sort(key=lambda v: v["name"].lower())
    return items


def _safe_voice_path(filename: str) -> str | None:
    """Resolve `filename` to a real audio file inside VOICES_DIR (no traversal)."""
    base = os.path.basename(filename or "")
    if os.path.splitext(base)[1].lower() not in AUDIO_EXTS:
        return None
    path = os.path.join(VOICES_DIR, base)
    return path if os.path.isfile(path) else None


def _audio_duration(path: str) -> float | None:
    """Fast duration probe for upload validation — never fully decodes large files."""
    ext = os.path.splitext(path)[1].lower()
    try:
        import soundfile as sf

        info = sf.info(path)
        if info.samplerate:
            return info.frames / float(info.samplerate)
    except Exception:  # noqa: BLE001
        pass
    if ext == ".wav":
        try:
            import wave

            with wave.open(path, "rb") as wf:
                rate = wf.getframerate()
                if rate:
                    return wf.getnframes() / float(rate)
        except Exception:  # noqa: BLE001
            pass
    if ext in {".mp3", ".m4a", ".ogg", ".flac", ".webm"}:
        try:
            import json as _json
            import subprocess

            proc = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "quiet",
                    "-print_format",
                    "json",
                    "-show_format",
                    path,
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout:
                dur = float(_json.loads(proc.stdout)["format"]["duration"])
                if dur > 0:
                    return dur
        except Exception:  # noqa: BLE001
            pass
    return None


hub = Hub()


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=hub.load_agent, daemon=True).start()
    yield


app = FastAPI(title="Qwen3 Voice Agent", lifespan=lifespan)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/config")
def get_config() -> dict:
    return hub.get_config()


@app.post("/config")
def set_config(data: dict = Body(...)) -> dict:
    return hub.set_config(data or {})


@app.get("/personalities")
def list_personalities() -> dict:
    return hub.list_personalities()


@app.post("/personalities/activate")
def activate_personality(data: dict = Body(...)) -> dict:
    return hub.activate_personality(str((data or {}).get("id", "")))


@app.post("/personalities/save")
def save_personality(data: dict = Body(...)) -> dict:
    return hub.save_personality(data or {})


@app.post("/personalities/delete")
def delete_personality(data: dict = Body(...)) -> dict:
    return hub.delete_personality(str((data or {}).get("id", "")))


@app.post("/personalities/import")
def import_personality(data: dict = Body(...)) -> dict:
    return hub.import_personality(data or {})


@app.post("/personalities/import-png")
async def import_personality_png(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    if not data:
        return {"ok": False, "error": "empty file"}
    return hub.import_personality_png(data)


@app.post("/personalities/build")
def build_character_card(data: dict = Body(...)) -> dict:
    return hub.build_character_card(str((data or {}).get("prompt", "")))


@app.get("/personalities/export")
def export_personality(id: str = "") -> dict:
    return hub.export_personality(id)


@app.get("/spectrum")
def spectrum() -> dict:
    if hub.agent is None:
        return {"speaking": False, "level": 0.0, "bands": []}
    p = hub.agent.playback
    return {"speaking": p.is_playing(), "level": p.level(), "bands": p.spectrum()}


@app.post("/start")
def start() -> dict:
    return hub.start()


@app.post("/stop")
def stop() -> dict:
    return hub.stop()


@app.get("/memory")
def memory_status() -> dict:
    return hub.memory_status()


@app.post("/memory-edit")
def memory_edit(data: dict = Body(...)) -> dict:
    return hub.memory_edit(data or {})


@app.post("/memory-approve")
def memory_approve(data: dict = Body(...)) -> dict:
    return hub.memory_approve(str((data or {}).get("id", "")))


@app.post("/memory-reject")
def memory_reject(data: dict = Body(...)) -> dict:
    return hub.memory_reject(str((data or {}).get("id", "")))


@app.post("/session-search")
def session_search(data: dict = Body(...)) -> dict:
    return hub.session_search(str((data or {}).get("query", "")))


@app.get("/memory-explore")
def memory_explore(
    db: str = "state",
    limit: int = 50,
    offset: int = 0,
    session_id: str = "",
    scope: str = "",
) -> dict:
    return hub.memory_explore(db, limit, offset, session_id, scope)


@app.get("/memory-skill")
def memory_skill(name: str = "") -> dict:
    return hub.read_skill(name)


@app.get("/tools-status")
def tools_status() -> dict:
    return hub.tools_status()


@app.get("/vts-status")
def vts_status() -> dict:
    return hub.vts_status()


@app.post("/vts-map")
def vts_map(data: dict = Body(...)) -> dict:
    return hub.set_vts_map(data.get("map", data) or {})


@app.post("/vts-test")
def vts_test(data: dict = Body(...)) -> dict:
    return hub.test_vts_action(str(data.get("action", "")))


@app.get("/voices")
def list_voices() -> dict:
    return {"ok": True, "voices": _list_voices(), "current": hub.current_voice}


@app.get("/voice-audio/{filename}")
def voice_audio(filename: str):
    path = _safe_voice_path(filename)
    if path is None:
        return {"ok": False, "error": "not found"}
    return FileResponse(path)


@app.post("/select-voice")
def select_voice(data: dict = Body(...)) -> dict:
    path = _safe_voice_path((data or {}).get("file", ""))
    if path is None:
        return {"ok": False, "error": "voice file not found"}
    return hub.set_voice(path)


@app.post("/upload-voice")
async def upload_voice(file: UploadFile = File(...)) -> dict:
    os.makedirs(VOICES_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1].lower() or ".wav"
    if ext not in {".wav", ".flac", ".ogg", ".mp3", ".m4a", ".webm"}:
        return {"ok": False, "error": f"Unsupported file type: {ext}"}
    import time as _time

    dest = os.path.join(VOICES_DIR, f"upload_{int(_time.time())}{ext}")
    data = await file.read()
    if not data:
        return {"ok": False, "error": "empty file"}
    with open(dest, "wb") as fh:
        fh.write(data)

    dur = _audio_duration(dest)
    if dur is None:
        os.remove(dest)
        return {"ok": False, "error": "Could not read that audio file."}
    if dur < 2.0:
        return {"ok": False, "error": "Clip too short; use ~10-20s of clean speech."}

    result = hub.set_voice(dest)
    if result.get("ok"):
        result["duration"] = round(dur, 1)
    return result


@app.get("/events")
def events() -> StreamingResponse:
    q = hub.subscribe()

    def gen():
        try:
            while True:
                try:
                    event = q.get(timeout=15.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    # Heartbeat keeps the connection (and any proxies) alive.
                    yield ": keep-alive\n\n"
        finally:
            hub.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream")


if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def main() -> None:
    parser = argparse.ArgumentParser(description="Qwen3 voice agent web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7861)
    args = parser.parse_args()

    import uvicorn

    log.info("open http://%s:%s", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
