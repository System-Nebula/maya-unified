"""qwen3 VoiceAgent routes under /api/voice/agent/* + SSE events."""

from __future__ import annotations

import json
import os
import queue

from fastapi import Body, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse

from services.paths import VOICE_RUNTIME, voices_dir
from services.auth.scope import scoped_operator_id
from services.voice.hub import hub

from server import (  # noqa: E402
    AUDIO_EXTS,
    _audio_duration,
    _list_voices,
    _safe_voice_path,
)

VOICES_DIR = str(voices_dir()) if VOICE_RUNTIME.is_dir() else "voices"


def _operator_id(request: Request) -> str:
    op = getattr(request.state, "operator", None)
    if op is None:
        return ""
    return str(op.id)


def _apply_operator_scope(request: Request, operator_id: str = "") -> str:
    oid = scoped_operator_id(request, operator_id)
    if oid:
        hub.apply_operator_context(oid)
    return oid


def register_agent_routes(app) -> None:
    prefix = "/api/voice/agent"

    @app.get(f"{prefix}/status")
    def agent_status(request: Request) -> dict:
        oid = _operator_id(request)
        snap = hub.agent_capabilities(oid or None)
        llm = hub.llm_status(oid or None)
        health = snap["health"]
        capabilities = snap["capabilities"]
        session_running = False
        if hub.ready and hub.agent is not None and oid:
            lease = hub.voice_lease
            session_running = (
                hub.agent.is_session_running()
                and lease is not None
                and lease.kind == "operator"
                and lease.context_id == oid
            )
        return {
            "ok": True,
            "ready": hub.ready,
            "status": hub.status,
            "session_running": session_running,
            "error": getattr(hub, "last_error", "") or None,
            "llm_ok": llm.get("ok", False),
            "llm_ready": snap["llm_ready"],
            "llm_error": llm.get("error"),
            "llm_base_url": llm.get("base_url"),
            "llm_model": llm.get("model"),
            "llm_provider": llm.get("provider"),
            "llm_health": health,
            "capabilities": capabilities,
            **hub.lease_status(),
        }

    @app.get(f"{prefix}/conversation")
    def agent_conversation(request: Request) -> dict:
        oid = _operator_id(request)
        return hub.conversation_state(oid or None)

    @app.post(f"{prefix}/chat")
    def agent_chat(request: Request, data: dict = Body(...)) -> dict:
        return hub.chat_text(str((data or {}).get("text", "")), operator_id=_operator_id(request) or None)

    @app.post(f"{prefix}/speak")
    def agent_speak(request: Request, data: dict = Body(...)) -> dict:
        payload = data or {}
        instruct = str(payload.get("instruct", "") or "").strip() or None
        return hub.speak_text(
            str(payload.get("text", "")),
            instruct=instruct,
            operator_id=_operator_id(request) or None,
        )

    @app.post(f"{prefix}/tts")
    def agent_tts(request: Request, data: dict = Body(...)):
        payload = data or {}
        instruct = str(payload.get("instruct", "") or "").strip() or None
        text = str(payload.get("text", "")).strip()
        if not text:
            return JSONResponse({"ok": False, "error": "empty text"}, status_code=400)
        if not hub.ready or hub.agent is None:
            return JSONResponse(
                {"ok": False, "error": hub.last_error or "agent not ready"},
                status_code=503,
            )
        voice = hub.agent.voice
        if voice is None or not getattr(voice, "available", True):
            return JSONResponse(
                {
                    "ok": False,
                    "error": getattr(voice, "degrade_reason", "TTS unavailable"),
                },
                status_code=503,
            )
        try:
            wav_bytes, _sr = hub.render_speech(
                text,
                instruct=instruct,
                operator_id=_operator_id(request) or None,
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)
        return Response(content=wav_bytes, media_type="audio/wav")

    @app.post(f"{prefix}/webllm/ready")
    def webllm_ready(data: dict = Body(default_factory=dict)) -> dict:
        from services.llm import webllm_broker

        webllm_broker.mark_browser_ready(bool((data or {}).get("ready", True)))
        return {"ok": True}

    @app.post(f"{prefix}/webllm/fulfill")
    def webllm_fulfill(data: dict = Body(...)) -> dict:
        from services.llm import webllm_broker

        payload = data or {}
        ok = webllm_broker.fulfill(
            str(payload.get("id", "")),
            chunk=str(payload.get("chunk", "")),
            done=bool(payload.get("done")),
            error=str(payload.get("error", "")),
        )
        return {"ok": ok}

    @app.get(f"{prefix}/config")
    def get_config(request: Request) -> dict:
        return hub.get_config(_operator_id(request) or None)

    @app.post(f"{prefix}/config")
    def set_config(data: dict = Body(...)) -> dict:
        return hub.set_config(data or {})

    @app.get(f"{prefix}/events")
    def events(request: Request) -> StreamingResponse:
        oid = _operator_id(request) or None
        q = hub.subscribe(operator_id=oid)

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
    def start(request: Request) -> dict:
        oid = _operator_id(request)
        if not oid:
            return {"ok": False, "error": "not authenticated"}
        return hub.start(operator_id=oid)

    @app.post(f"{prefix}/stop")
    def stop(request: Request) -> dict:
        oid = _operator_id(request)
        return hub.stop(operator_id=oid or None)

    @app.get(f"{prefix}/spectrum")
    def spectrum() -> dict:
        if hub.agent is None:
            return {"speaking": False, "level": 0.0, "bands": []}
        p = hub.agent.playback
        return {"speaking": p.is_playing(), "level": p.level(), "bands": p.spectrum()}

    @app.get(f"{prefix}/personalities")
    def list_personalities(request: Request) -> dict:
        oid = _operator_id(request)
        if oid:
            return hub.list_personalities_for_operator(oid)
        return hub.list_personalities()

    @app.post(f"{prefix}/personalities/activate")
    def activate_personality(request: Request, data: dict = Body(...)) -> dict:
        pid = str((data or {}).get("id", ""))
        oid = _operator_id(request)
        if oid:
            return hub.activate_personality_for_operator(oid, pid)
        return hub.activate_personality(pid)

    @app.post(f"{prefix}/personalities/save")
    def save_personality(request: Request, data: dict = Body(...)) -> dict:
        oid = _operator_id(request)
        if oid:
            hub.apply_operator_context(oid)
        return hub.save_personality(data or {})

    @app.post(f"{prefix}/personalities/delete")
    def delete_personality(request: Request, data: dict = Body(...)) -> dict:
        oid = _operator_id(request)
        if oid:
            hub.apply_operator_context(oid)
        return hub.delete_personality(str((data or {}).get("id", "")))

    @app.post(f"{prefix}/personalities/import")
    def import_personality(request: Request, data: dict = Body(...)) -> dict:
        oid = _operator_id(request)
        if oid:
            hub.apply_operator_context(oid)
        return hub.import_personality(data or {})

    @app.post(f"{prefix}/personalities/import-png")
    async def import_personality_png(request: Request, file: UploadFile = File(...)) -> dict:
        oid = _operator_id(request)
        if oid:
            hub.apply_operator_context(oid)
        data = await file.read()
        if not data:
            return {"ok": False, "error": "empty file"}
        return hub.import_personality_png(data)

    @app.post(f"{prefix}/personalities/build")
    def build_character_card(data: dict = Body(...)) -> dict:
        return hub.build_character_card(str((data or {}).get("prompt", "")))

    @app.get(f"{prefix}/personalities/export")
    def export_personality(request: Request, id: str = "") -> dict:
        oid = _operator_id(request)
        if oid:
            hub.apply_operator_context(oid)
        return hub.export_personality(id)

    @app.get(f"{prefix}/memory")
    def memory_status(request: Request) -> dict:
        oid = _operator_id(request)
        if oid:
            hub.apply_operator_context(oid)
        return hub.memory_status()

    @app.post(f"{prefix}/memory-edit")
    def memory_edit(request: Request, data: dict = Body(...)) -> dict:
        oid = _operator_id(request)
        if oid:
            hub.apply_operator_context(oid)
        return hub.memory_edit(data or {})

    @app.post(f"{prefix}/memory-approve")
    def memory_approve(request: Request, data: dict = Body(...)) -> dict:
        oid = _operator_id(request)
        if oid:
            hub.apply_operator_context(oid)
        return hub.memory_approve(str((data or {}).get("id", "")))

    @app.post(f"{prefix}/memory-reject")
    def memory_reject(request: Request, data: dict = Body(...)) -> dict:
        oid = _operator_id(request)
        if oid:
            hub.apply_operator_context(oid)
        return hub.memory_reject(str((data or {}).get("id", "")))

    @app.post(f"{prefix}/session-search")
    def session_search(request: Request, data: dict = Body(...)) -> dict:
        oid = _operator_id(request)
        if oid:
            hub.apply_operator_context(oid)
        return hub.session_search(str((data or {}).get("query", "")))

    @app.get(f"{prefix}/memory-explore")
    def memory_explore(
        request: Request,
        db: str = "state",
        limit: int = 50,
        offset: int = 0,
        session_id: str = "",
        scope: str = "",
        operator_id: str = "",
    ) -> dict:
        _apply_operator_scope(request, operator_id)
        return hub.memory_explore(db, limit, offset, session_id, scope)

    @app.get(f"{prefix}/memory-skill")
    def memory_skill(request: Request, name: str = "") -> dict:
        oid = _operator_id(request)
        if oid:
            hub.apply_operator_context(oid)
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
    def select_voice(request: Request, data: dict = Body(...)) -> dict:
        oid = _operator_id(request)
        if oid:
            hub.apply_operator_context(oid)
        path = _safe_voice_path((data or {}).get("file", ""))
        if path is None:
            return {"ok": False, "error": "voice file not found"}
        return hub.set_voice(path)

    @app.post(f"{prefix}/upload-voice")
    async def upload_voice(request: Request, file: UploadFile = File(...)) -> dict:
        oid = _operator_id(request)
        if oid:
            hub.apply_operator_context(oid)
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
