"""VTuber support via the VTube Studio plugin WebSocket API.

Two features, adapted from the approach in Beginner-Friendly-Ai-Vtuber:

  - Expressions: trigger a VTS hotkey based on the reply's emotion. Hotkeys are
    auto-mapped to emotions by matching keywords in their names (a hotkey named
    "Happy" maps to the "happy" emotion, etc.).
  - Lip-sync: inject the mouth parameter (default "MouthOpen") in real time from
    the live playback amplitude, so the model's mouth moves while the agent talks.

VTube Studio must be running with the plugin API enabled (Settings -> Start API,
default port 8001). The first connection pops an allow-plugin prompt in VTS; the
returned token is cached so later runs authenticate silently.

Everything here is best-effort and isolated: if VTS isn't running or the API is
off, the client just keeps retrying in the background and the voice agent works
exactly as before.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Callable, Optional

from config import CONFIG, VTSConfig

# Map an emotion to keywords that might appear in a VTS hotkey name. Order matters:
# the first emotion whose keywords are detected wins.
EMOTION_KEYWORDS: dict[str, list[str]] = {
    "angry": ["angry", "mad", "upset", "furious", "annoy", "irritat", "rage", "grump"],
    "sad": ["sad", "cry", "tear", "depress", "somber", "sorrow", "gloom", "unhappy", "melanchol", "down"],
    "surprised": ["surprise", "shock", "gasp", "astonish", "amazed", "wow", "startle"],
    "happy": ["happy", "joy", "smile", "laugh", "grin", "cheer", "amused", "excited",
              "delight", "glad", "playful", "giggl", "warm", "fun"],
    "thinking": ["think", "hmm", "ponder", "curious", "wonder", "consider", "idea", "confus"],
    "neutral": ["neutral", "calm", "default", "normal", "rest", "idle"],
}


# The emotions we expose for mapping in the UI, in a sensible display order.
EMOTIONS: list[str] = ["happy", "sad", "angry", "surprised", "thinking", "neutral"]


def detect_emotion(*texts: str) -> str:
    """Pick an emotion label from one or more text fragments (cue + reply)."""
    blob = " ".join(t for t in texts if t).lower()
    if not blob.strip():
        return "neutral"
    for emotion, words in EMOTION_KEYWORDS.items():
        if any(w in blob for w in words):
            return emotion
    return "neutral"


class VTubeStudioClient:
    API_NAME = "VTubeStudioPublicAPI"
    API_VERSION = "1.0"

    def __init__(self, cfg: VTSConfig | None = None, on_event: Optional[Callable[[dict], None]] = None):
        self.cfg = cfg or CONFIG.vts
        self.on_event = on_event
        self.url = f"ws://{self.cfg.host}:{self.cfg.port}"

        self.ws = None
        self.authenticated = False
        self.token = self._load_token()

        # name(lower) -> hotkeyID, and emotion -> hotkeyID
        self.hotkeys: dict[str, str] = {}
        self.hotkey_names: list[str] = []
        self.emotion_hotkeys: dict[str, str] = {}
        self.last_expression: Optional[str] = None

        # Expression files (.exp3.json) discovered on the model: name(lower) -> file.
        self.expressions: dict[str, str] = {}
        self.expression_names: list[str] = []
        self._active_expr_file: Optional[str] = None

        # Manual emotion -> action-name overrides (action = hotkey or expression
        # name). Persisted so the user's mapping survives restarts.
        self.emotion_map: dict[str, str] = self._load_map()

        self._level_fn: Optional[Callable[[], float]] = None
        self._stop = threading.Event()
        self._net_thread: Optional[threading.Thread] = None
        self._pump_thread: Optional[threading.Thread] = None
        self._last_mouth = -1.0

    # ----- lifecycle --------------------------------------------------------

    def start(self, level_fn: Optional[Callable[[], float]] = None) -> None:
        self._level_fn = level_fn
        self._stop.clear()
        self._net_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._net_thread.start()
        self._pump_thread = threading.Thread(target=self._mouth_loop, daemon=True)
        self._pump_thread.start()

    def close(self) -> None:
        self._stop.set()
        try:
            if self.ws is not None:
                self.ws.close()
        except Exception:  # noqa: BLE001
            pass
        self.authenticated = False

    def _run_loop(self) -> None:
        import websocket  # websocket-client

        while not self._stop.is_set():
            try:
                self.ws = websocket.WebSocketApp(
                    self.url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self.ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as exc:  # noqa: BLE001
                print(f"[vts] connection error: {exc}")
            self.authenticated = False
            if self._stop.is_set():
                break
            time.sleep(3.0)  # reconnect backoff

    # ----- websocket callbacks ---------------------------------------------

    def _on_open(self, ws) -> None:
        print(f"[vts] connected to VTube Studio at {self.url}")
        self._emit_status()
        if self.token:
            self._authenticate(self.token)
        else:
            self._send("auth_token", "AuthenticationTokenRequest", {
                "pluginName": self.cfg.plugin_name,
                "pluginDeveloper": self.cfg.plugin_developer,
            })

    def _on_message(self, ws, message: str) -> None:
        try:
            msg = json.loads(message)
        except Exception:  # noqa: BLE001
            return
        mtype = msg.get("messageType", "")
        data = msg.get("data", {}) or {}

        if mtype == "AuthenticationTokenResponse":
            token = data.get("authenticationToken")
            if token:
                self._save_token(token)
                self.token = token
                self._authenticate(token)
        elif mtype == "AuthenticationResponse":
            self.authenticated = bool(data.get("authenticated"))
            if self.authenticated:
                print("[vts] authenticated with VTube Studio.")
                self._request_hotkeys()
                self._request_expressions()
            else:
                print(f"[vts] authentication failed: {data.get('reason')}")
            self._emit_status()
        elif mtype == "HotkeysInCurrentModelResponse":
            self._ingest_hotkeys(data.get("availableHotkeys", []) or [])
            self._emit_status()
        elif mtype == "ExpressionStateResponse":
            self._ingest_expressions(data.get("expressions", []) or [])
            self._emit_status()
        elif mtype == "APIError":
            print(f"[vts] API error: {data.get('message')}")

    def _on_error(self, ws, error) -> None:
        print(f"[vts] websocket error: {error}")

    def _on_close(self, ws, *args) -> None:
        self.authenticated = False
        self._emit_status()

    # ----- requests ---------------------------------------------------------

    def _authenticate(self, token: str) -> None:
        self._send("auth", "AuthenticationRequest", {
            "pluginName": self.cfg.plugin_name,
            "pluginDeveloper": self.cfg.plugin_developer,
            "authenticationToken": token,
        })

    def _request_hotkeys(self) -> None:
        self._send("hotkeys", "HotkeysInCurrentModelRequest", {})

    def _request_expressions(self) -> None:
        self._send("expressions", "ExpressionStateRequest", {"details": True})

    def _ingest_hotkeys(self, hotkeys: list[dict]) -> None:
        self.hotkeys = {}
        self.hotkey_names = []
        for hk in hotkeys:
            name = (hk.get("name") or "").strip()
            hid = hk.get("hotkeyID")
            if name and hid:
                self.hotkeys[name.lower()] = hid
                self.hotkey_names.append(name)
        # Auto-map emotions to the first hotkey whose name matches a keyword.
        self.emotion_hotkeys = {}
        for emotion, words in EMOTION_KEYWORDS.items():
            for name_l, hid in self.hotkeys.items():
                if any(w in name_l for w in words):
                    self.emotion_hotkeys[emotion] = hid
                    break
        print(f"[vts] {len(self.hotkey_names)} hotkeys, "
              f"auto emotion map: {sorted(self.emotion_hotkeys)}")
        self._auto_fill_map()

    def _ingest_expressions(self, expressions: list[dict]) -> None:
        self.expressions = {}
        self.expression_names = []
        for ex in expressions:
            name = (ex.get("name") or os.path.splitext(ex.get("file", ""))[0]).strip()
            file = ex.get("file")
            if name and file:
                self.expressions[name.lower()] = file
                self.expression_names.append(name)
        # Auto-map any emotion not already covered by a hotkey to a matching
        # expression file (e.g. an expression literally named "happy").
        for emotion, words in EMOTION_KEYWORDS.items():
            if emotion in self.emotion_hotkeys:
                continue
            for name_l in self.expressions:
                if any(w in name_l for w in words):
                    self.emotion_hotkeys.setdefault(emotion, f"expr:{name_l}")
                    break
        print(f"[vts] {len(self.expression_names)} expression files: "
              f"{self.expression_names}")
        self._auto_fill_map()

    def _auto_fill_map(self) -> None:
        """If the user hasn't mapped an emotion yet, but only generic actions
        exist, leave it blank. If a keyword match exists, seed the manual map so
        the UI shows a sensible default the user can override."""
        actions_lower = {n.lower() for n in self.action_names}
        for emotion in EMOTIONS:
            if self.emotion_map.get(emotion):
                continue
            auto = self.emotion_hotkeys.get(emotion)
            if not auto:
                continue
            # Resolve auto target back to an action name for display.
            if isinstance(auto, str) and auto.startswith("expr:"):
                ename = auto[5:]
                if ename in self.expressions:
                    # store the original-cased name
                    for n in self.expression_names:
                        if n.lower() == ename:
                            self.emotion_map[emotion] = n
                            break
            else:
                for n in self.hotkey_names:
                    if self.hotkeys.get(n.lower()) == auto:
                        self.emotion_map[emotion] = n
                        break
        if actions_lower:
            self._save_map()

    def _send(self, request_id: str, message_type: str, data: dict | None = None) -> bool:
        if not self._connected():
            return False
        payload = {
            "apiName": self.API_NAME,
            "apiVersion": self.API_VERSION,
            "requestID": request_id,
            "messageType": message_type,
        }
        if data is not None:
            payload["data"] = data
        try:
            self.ws.send(json.dumps(payload))
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"[vts] send error: {exc}")
            return False

    def _connected(self) -> bool:
        return bool(self.ws and getattr(self.ws, "sock", None) and self.ws.sock.connected)

    # ----- expressions ------------------------------------------------------

    @property
    def action_names(self) -> list[str]:
        """All firable actions: hotkeys first, then expression files."""
        return list(self.hotkey_names) + list(self.expression_names)

    def trigger_emotion(self, emotion: str) -> Optional[str]:
        """Fire the action mapped to `emotion`, if any. Returns the emotion fired."""
        if not (self.authenticated and self.cfg.expressions):
            return None
        action = self.emotion_map.get(emotion)
        if not action:
            return None
        if self._fire_action(action):
            self.last_expression = emotion
            return emotion
        return None

    def _fire_action(self, name: str) -> bool:
        """Fire a hotkey or activate an expression file, by display name."""
        low = (name or "").strip().lower()
        if not low:
            return False
        if low in self.hotkeys:
            return self._send("hotkey", "HotkeyTriggerRequest",
                              {"hotkeyID": self.hotkeys[low]})
        if low in self.expressions:
            return self._activate_expression(self.expressions[low])
        return False

    def _activate_expression(self, file: str) -> bool:
        """Activate one expression file, deactivating the previous one so only
        one emotion face shows at a time."""
        if self._active_expr_file and self._active_expr_file != file:
            self._send("expr_off", "ExpressionActivationRequest",
                       {"expressionFile": self._active_expr_file, "active": False})
        ok = self._send("expr_on", "ExpressionActivationRequest",
                        {"expressionFile": file, "active": True})
        if ok:
            self._active_expr_file = file
        return ok

    def trigger_hotkey_by_name(self, name: str) -> bool:
        return self._fire_action(name)

    def test_action(self, name: str) -> bool:
        """Fire an action immediately for UI testing."""
        return self._fire_action(name)

    def set_emotion_map(self, mapping: dict) -> dict:
        """Replace the manual emotion -> action mapping and persist it."""
        clean: dict[str, str] = {}
        for emotion, action in (mapping or {}).items():
            if emotion in EMOTIONS:
                clean[emotion] = (action or "").strip()
        self.emotion_map = clean
        self._save_map()
        self._emit_status()
        return dict(self.emotion_map)

    # ----- lip-sync ---------------------------------------------------------

    def set_mouth(self, value: float) -> bool:
        if not self.authenticated:
            return False
        value = max(0.0, min(1.0, float(value)))
        if abs(value - self._last_mouth) < 0.015:
            return False
        self._last_mouth = value
        return self._send("mouth", "InjectParameterDataRequest", {
            "faceFound": False,
            "mode": "set",
            "parameterValues": [{"id": self.cfg.mouth_param, "value": value}],
        })

    def _mouth_loop(self) -> None:
        period = 1.0 / max(5, self.cfg.mouth_fps)
        smoothing = max(0.05, min(1.0, self.cfg.mouth_smoothing))
        prev = 0.0
        while not self._stop.is_set():
            if self.authenticated and self._level_fn is not None:
                try:
                    raw = float(self._level_fn() or 0.0)
                except Exception:  # noqa: BLE001
                    raw = 0.0
                amp = max(0.0, min(1.0, raw * self.cfg.mouth_gain))
                prev = prev * (1.0 - smoothing) + amp * smoothing
                self.set_mouth(prev)
            else:
                prev = 0.0
            time.sleep(period)

    # ----- status / token ---------------------------------------------------

    def status(self) -> dict:
        return {
            "enabled": True,
            "connected": self._connected(),
            "authenticated": self.authenticated,
            "host": self.cfg.host,
            "port": self.cfg.port,
            "hotkeys": list(self.hotkey_names),
            "expressions": list(self.expression_names),
            "actions": self.action_names,
            "emotions_list": EMOTIONS,
            "emotions": sorted(e for e in EMOTIONS if self.emotion_map.get(e)),
            "map": {e: self.emotion_map.get(e, "") for e in EMOTIONS},
            "last_expression": self.last_expression,
        }

    def _emit_status(self) -> None:
        if self.on_event is not None:
            try:
                self.on_event({"type": "vts", **self.status()})
            except Exception:  # noqa: BLE001
                pass

    def _token_path(self) -> str:
        path = self.cfg.token_file
        if not os.path.isabs(path):
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
        return path

    def _load_token(self) -> Optional[str]:
        try:
            path = self._token_path()
            if not os.path.exists(path):
                return None
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data.get("token") or data.get("authenticationToken")
        except Exception:  # noqa: BLE001
            return None

    def _save_token(self, token: str) -> None:
        try:
            with open(self._token_path(), "w", encoding="utf-8") as fh:
                json.dump({"token": token}, fh)
        except OSError as exc:
            print(f"[vts] could not save token: {exc}")

    def _map_path(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "vts_map.json")

    def _load_map(self) -> dict[str, str]:
        try:
            path = self._map_path()
            if not os.path.exists(path):
                return {}
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            return {e: str(v) for e, v in data.items() if e in EMOTIONS and v}
        except Exception:  # noqa: BLE001
            return {}

    def _save_map(self) -> None:
        try:
            with open(self._map_path(), "w", encoding="utf-8") as fh:
                json.dump({e: v for e, v in self.emotion_map.items() if v}, fh, indent=2)
        except OSError as exc:
            print(f"[vts] could not save map: {exc}")
