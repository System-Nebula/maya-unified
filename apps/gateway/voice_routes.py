"""qwen3 VoiceAgent routes under /api/voice/agent/* + SSE events."""

from __future__ import annotations

import json
import os
import queue

from fastapi import Body, File, UploadFile
from fastapi.responses import StreamingResponse

from services.paths import VOICE_RUNTIME
from services.voice.hub import hub

# Reuse voice file helpers from qwen3 server
from server import (  # noqa: E402
    AUDIO_EXTS,
    _audio_duration,
    _list_voices,
    _safe_voice_path,
)

VOICES_DIR = str(VOICE_RUNTIME / "voices") if VOICE_RUNTIME.is_dir() else "voices"


def register_agent_routes(app) -> None:
    prefix = "/api/voice/agent"

    @app.get(f"{prefix}/status")
    def agent_status() -> dict:
        llm = hub.llm_status() if hub.ready else {"ok": False, "error": "agent still loading"}
        return {
            "ok": True,
            "ready": hub.ready,
            "status": hub.status,
            "error": getattr(hub, "last_error", "") or None,
            "llm_ok": llm.get("ok", False),
            "llm_error": llm.get("error"),
            "llm_base_url": llm.get("base_url"),
            "llm_model": llm.get("model"),
            "llm_provider": llm.get("provider"),
        }

    @app.post(f"{prefix}/chat")
    def agent_chat(data: dict = Body(...)) -> dict:
        return hub.chat_text(str((data or {}).get("text", "")))

    @app.get(f"{prefix}/config")
    def get_config() -> dict:
        return hub.get_config()

    @app.post(f"{prefix}/config")
    def set_config(data: dict = Body(...)) -> dict:
        return hub.set_config(data or {})

    @app.get(f"{prefix}/events")
    def events() -> StreamingResponse:
        q = hub.subscribe()

        def gen():
            try:
                while True:
                    try:
                        event = q.get(timeout=15.0)
                        yield f"data: {json.dumps(event)}\n\n"
                    except queue.Empty:
                        yield ": keep-alive\n\n"
            finally:
                hub.unsubscribe(q)

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post(f"{prefix}/start")
    def start() -> dict:
        return hub.start()

    @app.post(f"{prefix}/stop")
    def stop() -> dict:
        return hub.stop()

    @app.get(f"{prefix}/spectrum")
    def spectrum() -> dict:
        if hub.agent is None:
            return {"speaking": False, "level": 0.0, "bands": []}
        p = hub.agent.playback
        return {"speaking": p.is_playing(), "level": p.level(), "bands": p.spectrum()}

    @app.get(f"{prefix}/personalities")
    def list_personalities() -> dict:
        return hub.list_personalities()

    @app.post(f"{prefix}/personalities/activate")
    def activate_personality(data: dict = Body(...)) -> dict:
        return hub.activate_personality(str((data or {}).get("id", "")))

    @app.post(f"{prefix}/personalities/save")
    def save_personality(data: dict = Body(...)) -> dict:
        return hub.save_personality(data or {})

    @app.post(f"{prefix}/personalities/delete")
    def delete_personality(data: dict = Body(...)) -> dict:
        return hub.delete_personality(str((data or {}).get("id", "")))

    @app.post(f"{prefix}/personalities/import")
    def import_personality(data: dict = Body(...)) -> dict:
        return hub.import_personality(data or {})

    @app.post(f"{prefix}/personalities/import-png")
    async def import_personality_png(file: UploadFile = File(...)) -> dict:
        data = await file.read()
        if not data:
            return {"ok": False, "error": "empty file"}
        return hub.import_personality_png(data)

    @app.post(f"{prefix}/personalities/build")
    def build_character_card(data: dict = Body(...)) -> dict:
        return hub.build_character_card(str((data or {}).get("prompt", "")))

    @app.get(f"{prefix}/personalities/export")
    def export_personality(id: str = "") -> dict:
        return hub.export_personality(id)

    @app.get(f"{prefix}/memory")
    def memory_status() -> dict:
        return hub.memory_status()

    @app.post(f"{prefix}/memory-edit")
    def memory_edit(data: dict = Body(...)) -> dict:
        return hub.memory_edit(data or {})

    @app.post(f"{prefix}/memory-approve")
    def memory_approve(data: dict = Body(...)) -> dict:
        return hub.memory_approve(str((data or {}).get("id", "")))

    @app.post(f"{prefix}/memory-reject")
    def memory_reject(data: dict = Body(...)) -> dict:
        return hub.memory_reject(str((data or {}).get("id", "")))

    @app.post(f"{prefix}/session-search")
    def session_search(data: dict = Body(...)) -> dict:
        return hub.session_search(str((data or {}).get("query", "")))

    @app.get(f"{prefix}/memory-explore")
    def memory_explore(
        db: str = "state",
        limit: int = 50,
        offset: int = 0,
        session_id: str = "",
        scope: str = "",
    ) -> dict:
        return hub.memory_explore(db, limit, offset, session_id, scope)

    @app.get(f"{prefix}/memory-skill")
    def memory_skill(name: str = "") -> dict:
        return hub.read_skill(name)

    @app.get(f"{prefix}/tools-status")
    def tools_status() -> dict:
        return hub.tools_status()

    @app.get(f"{prefix}/vts-status")
    def vts_status() -> dict:
        return hub.vts_status()

    @app.post(f"{prefix}/vts-map")
    def vts_map(data: dict = Body(...)) -> dict:
        return hub.set_vts_map(data.get("map", data) or {})

    @app.post(f"{prefix}/vts-test")
    def vts_test(data: dict = Body(...)) -> dict:
        return hub.test_vts_action(str(data.get("action", "")))

    @app.get(f"{prefix}/voices")
    def list_voices() -> dict:
        return {"ok": True, "voices": _list_voices(), "current": hub.current_voice}

    @app.post(f"{prefix}/select-voice")
    def select_voice(data: dict = Body(...)) -> dict:
        path = _safe_voice_path((data or {}).get("file", ""))
        if path is None:
            return {"ok": False, "error": "voice file not found"}
        return hub.set_voice(path)

    @app.post(f"{prefix}/upload-voice")
    async def upload_voice(file: UploadFile = File(...)) -> dict:
        os.makedirs(VOICES_DIR, exist_ok=True)
        ext = os.path.splitext(file.filename or "")[1].lower() or ".wav"
        if ext not in AUDIO_EXTS:
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
