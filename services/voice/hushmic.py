"""DPDFNet / HushMic speech enhancement (shared by duplex + Discord VC)."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Hashable

import numpy as np

log = logging.getLogger("maya-unified.voice.hushmic")

EnhancerKey = tuple[Hashable, ...]

DEFAULT_MAX_ENHANCERS = 32
DEFAULT_TTL_S = 600.0


def browser_key(session_id: str | None, *, connection_id: str | None = None) -> EnhancerKey:
    """Namespaced browser enhancer key — never bare int 0."""
    sid = (session_id or "").strip() or "default"
    cid = (connection_id or "").strip()
    return ("browser", sid, cid) if cid else ("browser", sid)


def discord_key(user_id: int, *, guild_id: int | str | None = None) -> EnhancerKey:
    gid = str(guild_id if guild_id is not None else "0")
    return ("discord", gid, int(user_id))


def coerce_key(key: EnhancerKey | int | None) -> EnhancerKey:
    if isinstance(key, tuple) and key:
        return key
    if key is None:
        raise ValueError("enhancer key is required (refusing bare None)")
    # Legacy int ids map into an isolated namespace (not browser, not discord).
    return ("legacy", int(key))


def stereo_48k_to_mono_48k_bytes(pcm_stereo: bytes) -> bytes:
    """Discord VC PCM (48 kHz stereo s16le) → mono 48 kHz s16le."""
    if not pcm_stereo:
        return b""
    raw = np.frombuffer(pcm_stereo, dtype=np.int16)
    if raw.size < 2:
        return pcm_stereo
    if raw.size % 2:
        raw = raw[:-1]
    mono = raw.reshape(-1, 2).astype(np.float32).mean(axis=1)
    return np.clip(mono, -32768, 32767).astype(np.int16).tobytes()


def downsample_mono_48k_to_16k_int16(pcm_mono_48k: bytes) -> np.ndarray:
    from services.voice.resample import downsample_mono_48k_to_16k_int16 as _down

    return _down(pcm_mono_48k)


class HushMicProcessor:
    """Streaming enhancer with namespaced per-source state and bounded LRU/TTL."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        model: str = "dpdfnet8_48khz_hr",
        sample_rate: int = 48000,
        max_enhancers: int = DEFAULT_MAX_ENHANCERS,
        ttl_s: float = DEFAULT_TTL_S,
        enhancer_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.model = model
        self.sample_rate = int(sample_rate)
        self.max_enhancers = max(1, int(max_enhancers))
        self.ttl_s = max(1.0, float(ttl_s))
        self._enhancer_factory = enhancer_factory
        self._enhancers: dict[EnhancerKey, Any] = {}
        self._last_used: dict[EnhancerKey, float] = {}
        self._lock = threading.RLock()
        self._evictions = 0

    def load(self) -> None:
        if not self.enabled:
            return
        # Warm a disposable browser default without colliding with Discord keys.
        self._ensure(browser_key("warmup"))

    def ready(self) -> bool:
        return not self.enabled or bool(self._enhancers)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "model": self.model,
                "ready": self.ready(),
                "sample_rate": self.sample_rate,
                "enhancer_count": len(self._enhancers),
                "max_enhancers": self.max_enhancers,
                "ttl_s": self.ttl_s,
                "evictions": self._evictions,
            }

    def enhancer_count(self) -> int:
        with self._lock:
            return len(self._enhancers)

    def has_key(self, key: EnhancerKey | int) -> bool:
        with self._lock:
            return coerce_key(key) in self._enhancers

    def _make_enhancer(self) -> Any:
        if self._enhancer_factory is not None:
            return self._enhancer_factory()
        from dpdfnet import StreamEnhancer

        return StreamEnhancer(model=self.model, verbose=False)

    def _purge_expired_unlocked(self, now: float) -> None:
        expired = [k for k, ts in self._last_used.items() if (now - ts) > self.ttl_s]
        for key in expired:
            self._drop_unlocked(key)

    def _evict_lru_unlocked(self) -> None:
        while len(self._enhancers) >= self.max_enhancers and self._last_used:
            oldest = min(self._last_used, key=self._last_used.get)
            self._drop_unlocked(oldest)

    def _drop_unlocked(self, key: EnhancerKey) -> None:
        enhancer = self._enhancers.pop(key, None)
        self._last_used.pop(key, None)
        if enhancer is not None:
            self._evictions += 1
            close = getattr(enhancer, "close", None) or getattr(enhancer, "reset", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001
                    pass

    def _ensure(self, key: EnhancerKey) -> Any:
        if not self.enabled:
            return None
        now = time.monotonic()
        with self._lock:
            self._purge_expired_unlocked(now)
            if key in self._enhancers:
                self._last_used[key] = now
                return self._enhancers[key]
            self._evict_lru_unlocked()
            enhancer = self._make_enhancer()
            self._enhancers[key] = enhancer
            self._last_used[key] = now
            return enhancer

    def reset(self, key: EnhancerKey | int | None = None, *, all_keys: bool = False) -> None:
        """Reset one enhancer. ``all_keys=True`` wipes every source (settings rebuild).

        ``key=None`` without ``all_keys`` is refused — browser reconnect must not
        wipe Discord (or other) enhancer state.
        """
        if all_keys:
            self.reset_all()
            return
        if key is None:
            log.warning("hushmic.reset(None) ignored — pass a namespaced key or all_keys=True")
            return
        ck = coerce_key(key)
        with self._lock:
            enhancer = self._enhancers.get(ck)
            if enhancer is not None:
                try:
                    enhancer.reset()
                except Exception:  # noqa: BLE001
                    pass
                self._last_used[ck] = time.monotonic()

    def reset_all(self) -> None:
        with self._lock:
            for enhancer in list(self._enhancers.values()):
                try:
                    enhancer.reset()
                except Exception:  # noqa: BLE001
                    pass
            self._enhancers.clear()
            self._last_used.clear()

    def close_key(self, key: EnhancerKey | int) -> None:
        ck = coerce_key(key)
        with self._lock:
            self._drop_unlocked(ck)

    def process_mono_48k(
        self,
        pcm_mono: bytes,
        *,
        key: EnhancerKey | int | None = None,
        user_id: int | None = None,
    ) -> bytes:
        if not self.enabled or not pcm_mono:
            return pcm_mono
        if key is None and user_id is not None:
            key = user_id
        if key is None:
            key = browser_key("default")
        enhancer = self._ensure(coerce_key(key))
        if enhancer is None:
            return pcm_mono
        samples = np.frombuffer(pcm_mono, dtype="<i2").astype(np.float32) / 32768.0
        enhanced = enhancer.process(samples, sample_rate=self.sample_rate)
        if enhanced.size == 0:
            return b""
        enhanced = np.clip(enhanced, -1.0, 1.0)
        return (enhanced * 32767.0).astype("<i2").tobytes()

    def process_discord_stereo_chunk(
        self,
        pcm_stereo: bytes,
        *,
        user_id: int,
        guild_id: int | str | None = None,
        key: EnhancerKey | None = None,
    ) -> bytes:
        """Enhance one Discord stereo frame; returns mono 48 kHz PCM."""
        mono = stereo_48k_to_mono_48k_bytes(pcm_stereo)
        ck = key if key is not None else discord_key(user_id, guild_id=guild_id)
        return self.process_mono_48k(mono, key=ck)

    def enhance_mono_utterance(
        self,
        pcm_mono: bytes,
        *,
        key: EnhancerKey | int | None = None,
        user_id: int | None = None,
        chunk_bytes: int = 1920,
    ) -> bytes:
        """Enhance mono PCM at ``sample_rate`` (chunked for streaming state)."""
        if not self.enabled:
            return pcm_mono
        if key is None and user_id is not None:
            key = user_id
        if key is None:
            key = browser_key("default")
        ck = coerce_key(key)
        self.reset(ck)
        out = bytearray()
        step = max(4, int(chunk_bytes))
        for offset in range(0, len(pcm_mono), step):
            chunk = pcm_mono[offset : offset + step]
            if len(chunk) < 4:
                continue
            enhanced = self.process_mono_48k(chunk, key=ck)
            if enhanced:
                out.extend(enhanced)
        return bytes(out)

    def enhance_discord_utterance(
        self,
        pcm_stereo: bytes,
        *,
        user_id: int,
        guild_id: int | str | None = None,
        key: EnhancerKey | None = None,
    ) -> bytes:
        """Enhance a full utterance (chunked for streaming enhancer state)."""
        if not self.enabled:
            return stereo_48k_to_mono_48k_bytes(pcm_stereo)
        ck = key if key is not None else discord_key(user_id, guild_id=guild_id)
        self.reset(ck)
        out = bytearray()
        # Discord/py-cord frames are typically 3840 bytes (20 ms @ 48 kHz stereo).
        step = 3840
        for offset in range(0, len(pcm_stereo), step):
            chunk = pcm_stereo[offset : offset + step]
            if len(chunk) < 4:
                continue
            enhanced = self.process_discord_stereo_chunk(
                chunk, user_id=user_id, guild_id=guild_id, key=ck
            )
            if enhanced:
                out.extend(enhanced)
        return bytes(out)


_shared: HushMicProcessor | None = None
_shared_lock = threading.Lock()


def reset_shared_processor() -> None:
    """Drop the singleton (settings rebuild / tests)."""
    global _shared
    with _shared_lock:
        if _shared is not None:
            try:
                _shared.reset_all()
            except Exception:  # noqa: BLE001
                pass
        _shared = None


def get_hushmic_processor(
    *,
    enabled: bool | None = None,
    model: str | None = None,
    force_reload: bool = False,
) -> HushMicProcessor:
    """Lazy singleton aligned with CONFIG.audio hushmic settings."""
    global _shared
    from config import CONFIG

    want_enabled = CONFIG.audio.hushmic_enabled if enabled is None else enabled
    want_model = CONFIG.audio.hushmic_model if model is None else (model or CONFIG.audio.hushmic_model)
    with _shared_lock:
        if force_reload and _shared is not None:
            try:
                _shared.reset_all()
            except Exception:  # noqa: BLE001
                pass
            _shared = None
        if _shared is not None:
            # Settings change: rebuild when enabled/model diverge.
            if _shared.enabled != want_enabled or _shared.model != want_model:
                try:
                    _shared.reset_all()
                except Exception:  # noqa: BLE001
                    pass
                _shared = None
        if _shared is None:
            _shared = HushMicProcessor(
                enabled=want_enabled,
                model=want_model,
                sample_rate=CONFIG.audio.hushmic_sample_rate,
            )
            try:
                _shared.load()
                if _shared.ready():
                    log.info("HushMic ready model=%s", want_model)
            except Exception as exc:  # noqa: BLE001
                log.warning("HushMic unavailable — passthrough: %s", exc)
                _shared = HushMicProcessor(enabled=False)
        return _shared
