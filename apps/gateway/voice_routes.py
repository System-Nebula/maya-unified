"""qwen3 VoiceAgent routes under /api/voice/agent/* + SSE events."""

from __future__ import annotations

import json
import os
import queue
import re
import threading
import time as _time

from fastapi import Body, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from services.paths import VOICE_RUNTIME, animations_dir, vrm_dir, voices_dir
from services.auth.scope import scoped_operator_id
from services.voice.hub import hub

from server import (  # noqa: E402
    AUDIO_EXTS,
    _audio_duration,
    _list_voices,
    _safe_voice_path,
)

VOICES_DIR = str(voices_dir()) if VOICE_RUNTIME.is_dir() else "voices"
VRM_DIR = str(vrm_dir())
ANIM_DIR = str(animations_dir())
VRM_EXTS = {".vrm"}
ANIM_EXTS = {".fbx", ".vrma"}
MAX_VOICE_UPLOAD_BYTES = 30 * 1024 * 1024
MAX_ANIM_UPLOAD_BYTES = 80 * 1024 * 1024
MANIFEST_NAME = "manifest.json"


def _manifest_path() -> str:
    return os.path.join(ANIM_DIR, MANIFEST_NAME)


def _load_anim_manifest() -> dict:
    path = _manifest_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_anim_manifest(data: dict) -> None:
    os.makedirs(ANIM_DIR, exist_ok=True)
    with open(_manifest_path(), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def _animation_catalog() -> list[dict]:
    manifest = _load_anim_manifest()
    out = []
    for fname in _list_animations():
        meta = manifest.get(fname, {})
        stem = os.path.splitext(fname)[0]
        label = str(meta.get("label") or stem.replace("_", " ").replace("-", " ")).strip()
        out.append({
            "file": fname,
            "label": label or stem,
            "description": str(meta.get("description") or "").strip(),
            "tags": meta.get("tags") if isinstance(meta.get("tags"), list) else [],
            "loop": bool(meta.get("loop", False)),
        })
    return out


def _safe_vrm_path(name: str) -> str | None:
    base = os.path.basename((name or "").strip())
    if not base.lower().endswith(".vrm"):
        return None
    path = os.path.join(VRM_DIR, base)
    if not os.path.isfile(path):
        return None
    real = os.path.realpath(path)
    root = os.path.realpath(VRM_DIR)
    if not real.startswith(root + os.sep) and real != root:
        return None
    return real


def _list_vrm_models() -> list[str]:
    os.makedirs(VRM_DIR, exist_ok=True)
    return sorted(
        f for f in os.listdir(VRM_DIR) if f.lower().endswith(".vrm") and os.path.isfile(os.path.join(VRM_DIR, f))
    )


def _safe_anim_path(name: str) -> str | None:
    base = os.path.basename((name or "").strip())
    ext = os.path.splitext(base)[1].lower()
    if ext not in ANIM_EXTS:
        return None
    path = os.path.join(ANIM_DIR, base)
    if not os.path.isfile(path):
        return None
    real = os.path.realpath(path)
    root = os.path.realpath(ANIM_DIR)
    if not real.startswith(root + os.sep) and real != root:
        return None
    return real


def _list_animations() -> list[str]:
    os.makedirs(ANIM_DIR, exist_ok=True)
    return sorted(
        f
        for f in os.listdir(ANIM_DIR)
        if os.path.splitext(f)[1].lower() in ANIM_EXTS and os.path.isfile(os.path.join(ANIM_DIR, f))
    )


def _voice_upload_stem(name: str, original_filename: str) -> str:
    raw = (name or "").strip()
    if not raw:
        raw = os.path.splitext(os.path.basename(original_filename or "voice"))[0]
    stem = re.sub(r"[^\w.\-]+", "_", raw).strip("._")
    return stem or "voice"


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
    async def upload_voice(
        request: Request,
        file: UploadFile = File(...),
        name: str = Form(""),
    ) -> dict:
        import asyncio

        os.makedirs(VOICES_DIR, exist_ok=True)
        ext = os.path.splitext(file.filename or "")[1].lower() or ".wav"
        if ext not in AUDIO_EXTS:
            return {"ok": False, "error": f"Unsupported file type: {ext} — use WAV, FLAC, MP3, or M4A"}
        data = await file.read()
        if not data:
            return {"ok": False, "error": "empty file"}
        if len(data) > MAX_VOICE_UPLOAD_BYTES:
            return {"ok": False, "error": "File too large (max 30 MB)"}
        stem = _voice_upload_stem(name, file.filename or "")
        dest = os.path.join(VOICES_DIR, f"{stem}{ext}")
        if os.path.exists(dest):
            dest = os.path.join(VOICES_DIR, f"{stem}_{int(_time.time())}{ext}")
        with open(dest, "wb") as fh:
            fh.write(data)
        dur = await asyncio.to_thread(_audio_duration, dest)
        if dur is None:
            os.remove(dest)
            return {
                "ok": False,
                "error": (
                    "Could not read that audio file. Use a WAV clip, or install ffmpeg "
                    "for MP3/M4A uploads."
                ),
            }
        if dur < 2.0:
            os.remove(dest)
            return {"ok": False, "error": "Clip too short; use ~10-20s of clean speech."}

        fname = os.path.basename(dest)
        return {
            "ok": True,
            "file": fname,
            "name": os.path.splitext(fname)[0],
            "voices": _list_voices(),
            "duration": round(dur, 1),
        }

    @app.get(f"{prefix}/vrm/models")
    def list_vrm_models() -> dict:
        return {"ok": True, "models": _list_vrm_models()}

    @app.get(f"{prefix}/vrm/file")
    def vrm_file(name: str = "") -> FileResponse:
        path = _safe_vrm_path(name)
        if path is None:
            raise HTTPException(status_code=404, detail="VRM model not found")
        return FileResponse(path, media_type="application/octet-stream", filename=os.path.basename(path))

    @app.post(f"{prefix}/upload-vrm")
    async def upload_vrm(file: UploadFile = File(...)) -> dict:
        os.makedirs(VRM_DIR, exist_ok=True)
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in VRM_EXTS:
            return {"ok": False, "error": f"Unsupported file type: {ext or '(none)'} — use .vrm"}
        import time as _time
        import re

        stem = re.sub(r"[^\w.\-]+", "_", os.path.splitext(os.path.basename(file.filename or "model"))[0]) or "model"
        dest = os.path.join(VRM_DIR, f"{stem}_{int(_time.time())}{ext}")
        data = await file.read()
        if not data:
            return {"ok": False, "error": "empty file"}
        if len(data) > 120 * 1024 * 1024:
            return {"ok": False, "error": "File too large (max 120 MB)"}
        with open(dest, "wb") as fh:
            fh.write(data)
        fname = os.path.basename(dest)
        return {"ok": True, "file": fname, "models": _list_vrm_models()}

    @app.get(f"{prefix}/animations")
    def list_animations() -> dict:
        return {"ok": True, "animations": _list_animations(), "catalog": _animation_catalog()}

    @app.patch(f"{prefix}/animation/meta")
    def patch_animation_meta(body: dict = Body(...)) -> dict:
        fname = os.path.basename(str(body.get("file") or "").strip())
        if not _safe_anim_path(fname):
            raise HTTPException(status_code=404, detail="Animation not found")
        manifest = _load_anim_manifest()
        entry = dict(manifest.get(fname, {}))
        if "label" in body:
            entry["label"] = str(body.get("label") or "").strip()
        if "description" in body:
            entry["description"] = str(body.get("description") or "").strip()
        if "tags" in body and isinstance(body.get("tags"), list):
            entry["tags"] = [str(t).strip() for t in body["tags"] if str(t).strip()]
        if "loop" in body:
            entry["loop"] = bool(body.get("loop"))
        manifest[fname] = entry
        _save_anim_manifest(manifest)
        return {"ok": True, "catalog": _animation_catalog()}

    @app.post(f"{prefix}/upload-animation")
    async def upload_animation(
        file: UploadFile = File(...),
        name: str = Form(""),
        label: str = Form(""),
        description: str = Form(""),
    ) -> dict:
        os.makedirs(ANIM_DIR, exist_ok=True)
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in ANIM_EXTS:
            return {"ok": False, "error": f"Unsupported file type: {ext or '(none)'} — use .fbx or .vrma"}
        raw_name = (name or "").strip() or os.path.splitext(os.path.basename(file.filename or "clip"))[0]
        stem = re.sub(r"[^\w.\-]+", "_", raw_name).strip("._") or "clip"
        dest_name = f"{stem}{ext}"
        dest = os.path.join(ANIM_DIR, dest_name)
        if os.path.isfile(dest):
            dest_name = f"{stem}_{int(_time.time())}{ext}"
            dest = os.path.join(ANIM_DIR, dest_name)
        data = await file.read()
        if not data:
            return {"ok": False, "error": "empty file"}
        if len(data) > MAX_ANIM_UPLOAD_BYTES:
            return {"ok": False, "error": "File too large (max 80 MB)"}
        with open(dest, "wb") as fh:
            fh.write(data)
        manifest = _load_anim_manifest()
        meta = {}
        if label.strip():
            meta["label"] = label.strip()
        if description.strip():
            meta["description"] = description.strip()
        if meta:
            manifest[dest_name] = meta
            _save_anim_manifest(manifest)
        return {"ok": True, "file": dest_name, "catalog": _animation_catalog()}

    @app.delete(f"{prefix}/animation")
    def delete_animation(name: str = "") -> dict:
        path = _safe_anim_path(name)
        if path is None:
            raise HTTPException(status_code=404, detail="Animation not found")
        fname = os.path.basename(path)
        try:
            os.remove(path)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        manifest = _load_anim_manifest()
        if fname in manifest:
            del manifest[fname]
            _save_anim_manifest(manifest)
        return {"ok": True, "deleted": fname, "catalog": _animation_catalog()}

    @app.get(f"{prefix}/animation/file")
    def animation_file(name: str = "") -> FileResponse:
        path = _safe_anim_path(name)
        if path is None:
            raise HTTPException(status_code=404, detail="Animation not found")
        return FileResponse(path, media_type="application/octet-stream", filename=os.path.basename(path))
