"""TTS + chat history for autonomous game play."""

from __future__ import annotations

import logging
import re
import threading

log = logging.getLogger("maya-unified.game.narration")

_BUTTON_NARRATION_RE = re.compile(
    r"\b(press(ing)?|mash(ing)?|hit(ting)?|push(ing)?|tap(ping)?)\b",
    re.I,
)
_VOICE_LINE_RE = re.compile(
    r"(?:^|[\n\r]+)\s*(?:[*_#]\s*)*VOICE:\s*[^\n\r]+",
    re.I,
)
_INLINE_VOICE_RE = re.compile(r"VOICE:\s*[^A-Z\n\r]+?(?=\s+[A-Z]|$)", re.I)


def _strip_voice_cues(text: str) -> str:
    body = (text or "").strip()
    if not body:
        return ""
    body = _VOICE_LINE_RE.sub("", body)
    body = _INLINE_VOICE_RE.sub("", body)
    return re.sub(r"\s{2,}", " ", body).strip()


def prepare_game_say(say: str) -> str:
    """Drop empty, VOICE cues, or pure button-read narration; keep streamer commentary."""
    text = _strip_voice_cues(say)
    if not text:
        return ""
    if _BUTTON_NARRATION_RE.search(text) and len(text) < 72:
        return ""
    return text


def speak_game_line(text: str, *, operator_id: str | None) -> None:
    """Speak a short in-character game narration line (non-blocking)."""
    line = prepare_game_say(text)
    if not line or not operator_id:
        return

    def _run() -> None:
        try:
            from services.voice.hub import hub

            if not hub.ready or hub.agent is None:
                log.debug("skip game TTS — agent not ready")
                return
            hub.speak_text(line, operator_id=operator_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("game TTS failed: %s", exc)

    threading.Thread(target=_run, daemon=True, name="game-tts").start()


def emit_game_chat_line(
    text: str,
    *,
    operator_id: str | None,
    action: str | None = None,
    turn: int | None = None,
) -> None:
    """Push a game commentary line to live chat + operator conversation history."""
    line = prepare_game_say(text)
    if not line or not operator_id:
        return

    def _run() -> None:
        try:
            from services.cmd.chat_bridge import _chat_event
            from services.ids import new_corr_id, new_message_id
            from services.operator_voice import context as op_ctx
            from services.voice.hub import hub

            corr_id = new_corr_id()
            message_id = new_message_id()
            payload: dict = {
                "type": "ai",
                "text": line,
                "mode": "game",
                "final": True,
            }
            if action:
                payload["game_action"] = action
            if turn is not None:
                payload["game_turn"] = turn
            hub.broadcast(
                _chat_event(payload, corr_id=corr_id, message_id=message_id),
                operator_id=operator_id,
            )
            op_ctx.append_turn(
                operator_id,
                "assistant",
                line,
                message_id=message_id,
                corr_id=corr_id,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("game chat emit failed: %s", exc)

    threading.Thread(target=_run, daemon=True, name="game-chat").start()
