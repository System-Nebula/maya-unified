"""FasterQwen3TTS streaming wrapper.

Wraps `faster_qwen3_tts.FasterQwen3TTS` behind one streaming interface that works
for both supported voice modes:

  - "clone"  -> generate_voice_clone_streaming(...)  (reference clip, ICL)
  - "custom" -> generate_custom_voice_streaming(...) (built-in speaker IDs)

`stream(text, stop)` yields (float32 mono numpy array, sample_rate) sub-chunks as
they are generated, so the caller can push each ~667ms chunk to the speakers while
the model keeps decoding. Checking `stop` between chunks makes barge-in cheap.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Iterator, Tuple

import numpy as np

from config import CONFIG, TTSConfig

from ref_text import clear_voice_prompt_cache, sync_clone_ref_text

log = logging.getLogger("voice-agent.tts")

_TTS_SETUP_HINT = (
    "Install voice deps from the repo root: make setup\n"
    "Or set VA_TTS_ENABLED=0 to run without voice output."
)


class NullTTS:
    """No-op TTS when disabled or when the model/package failed to load."""

    available = False

    def __init__(self, cfg: TTSConfig | None = None, *, reason: str = "TTS disabled") -> None:
        self.cfg = cfg or CONFIG.tts
        self.mode = self.cfg.mode.lower()
        self.clone_capable = False
        self.model_id = ""
        self.sr: int | None = None
        self.degrade_reason = reason

    def stream(
        self,
        text: str,
        stop: threading.Event | None = None,
        instruct: str | None = None,
        *,
        xvec_only: bool | None = None,
    ) -> Iterator[Tuple[np.ndarray, int]]:
        yield from ()

    def stream_timed(
        self,
        text: str,
        stop: threading.Event | None = None,
        instruct: str | None = None,
        *,
        xvec_only: bool | None = None,
    ) -> Iterator[Tuple[np.ndarray, int, dict[str, Any]]]:
        yield from ()

    def warmup(self) -> None:
        pass

    def set_reference(self, ref_audio: str, ref_text: str = "", warm: bool = True) -> None:
        raise RuntimeError(f"TTS unavailable: {self.degrade_reason}")

    def list_speakers(self) -> list[str]:
        return []


def load_tts(cfg: TTSConfig | None = None) -> Qwen3TTS | NullTTS:
    """Load Qwen3 TTS or return a stub when disabled/unavailable."""
    effective = cfg or CONFIG.tts
    if not effective.enabled:
        print("[tts] WARNING: VA_TTS_ENABLED=0 — voice output disabled.")
        return NullTTS(effective, reason="VA_TTS_ENABLED=0")

    try:
        return Qwen3TTS(effective)
    except ImportError as exc:
        reason = (
            f"faster-qwen3-tts not installed ({exc}).\n"
            f"{_TTS_SETUP_HINT}"
        )
        print(f"[tts] WARNING: {reason}")
        return NullTTS(effective, reason=reason)
    except FileNotFoundError as exc:
        reason = str(exc)
        print(f"[tts] WARNING: {reason}")
        return NullTTS(effective, reason=reason)
    except Exception as exc:  # noqa: BLE001 - CUDA/OOM/download failures
        reason = (
            f"Failed to load TTS model ({exc}).\n"
            f"{_TTS_SETUP_HINT}"
        )
        print(f"[tts] WARNING: {reason}")
        return NullTTS(effective, reason=reason)


def _to_float32_mono(wav) -> np.ndarray:
    """Normalize a torch tensor / numpy array of shape [C, N] or [N] to float32 mono."""
    try:
        import torch

        if isinstance(wav, torch.Tensor):
            wav = wav.detach().cpu().float().numpy()
    except ImportError:
        pass
    wav = np.asarray(wav, dtype=np.float32)
    if wav.ndim == 2:
        # [channels, samples] -> mono (assume the short axis is channels)
        axis = 0 if wav.shape[0] <= wav.shape[1] else 1
        wav = wav.mean(axis=axis)
    return np.ascontiguousarray(wav.reshape(-1), dtype=np.float32)


def _resolve_dtype(name: str):
    import torch

    return {
        "bf16": torch.bfloat16,
        "fp16": torch.float16,
        "fp32": torch.float32,
    }.get(name.lower(), torch.bfloat16)


class Qwen3TTS:
    available = True

    def _try_load_ref_text_sidecar(self) -> None:
        sync_clone_ref_text(self.cfg)

    def __init__(self, cfg: TTSConfig | None = None):
        self.cfg = cfg or CONFIG.tts
        mode = self.cfg.mode.lower()
        if mode not in {"clone", "custom"}:
            raise ValueError(f"Unknown VA_TTS_MODE: {self.cfg.mode!r} (use 'clone' or 'custom')")
        self.mode = mode

        # Only a Base (clone) model can voice-clone from a reference clip; a
        # CustomVoice model cannot, so uploads are only allowed in clone mode.
        self.clone_capable = self.mode == "clone"
        if self.mode == "clone":
            self.model_id = self.cfg.clone_model
            self._validate_clone()
        else:
            self.model_id = self.cfg.custom_model

        # Imported lazily so importing this module stays cheap without a GPU build.
        from faster_qwen3_tts import FasterQwen3TTS

        print(f"[tts] loading {self.model_id} (mode={self.mode})...")
        self.model = FasterQwen3TTS.from_pretrained(
            self.model_id,
            device=self.cfg.device,
            dtype=_resolve_dtype(self.cfg.dtype),
            attn_implementation="sdpa",
            max_seq_len=2048,
        )
        self.sr: int | None = None  # learned from the first generated chunk

        if self.mode == "clone":
            self._try_load_ref_text_sidecar()

        if self.cfg.warmup:
            self.warmup()

    def _validate_clone(self) -> None:
        if not os.path.exists(self.cfg.ref_audio):
            raise FileNotFoundError(
                f"Clone-mode reference clip not found: {self.cfg.ref_audio}\n"
                "Record a clean 10-20s WAV and point VA_TTS_REF_AUDIO at it, or use "
                "custom mode (VA_TTS_MODE=custom)."
            )
        if not self.cfg.xvec_only and not self.cfg.ref_text.strip():
            print(
                "[tts] WARNING: ICL clone mode works best with VA_TTS_REF_TEXT set to the "
                "exact transcript of the reference clip. Set it, or use VA_TTS_XVEC_ONLY=1."
            )

    # ----- generation -------------------------------------------------------

    def _seed(self) -> None:
        """Reset the RNG before each generation so consecutive sentences (separate
        generations) render with consistent timbre/energy instead of drifting."""
        if self.cfg.seed is None or self.cfg.seed < 0:
            return
        try:
            import torch

            torch.manual_seed(self.cfg.seed)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(self.cfg.seed)
        except Exception:  # noqa: BLE001
            pass

    def _effective_xvec_only(self, override: bool | None) -> bool:
        """Resolve x-vector vs full ICL for one generation."""
        if override is not None:
            return bool(override)
        return bool(self.cfg.xvec_only)

    def _generator(
        self, text: str, instruct: str | None = None, *, xvec_only: bool | None = None
    ):
        """Return the underlying faster-qwen3-tts streaming generator for `text`.

        `instruct` overrides the configured base description for this call (used by
        per-reply auto-delivery); pass None to fall back to `cfg.instruct`.
        `xvec_only` overrides `cfg.xvec_only` for this call (playback uses True to
        avoid replaying the reference clip at the start of each sentence).
        """
        self._seed()
        eff_instruct = (instruct if instruct is not None else self.cfg.instruct) or None
        if self.mode == "clone":
            use_xvec = self._effective_xvec_only(xvec_only)
            return self.model.generate_voice_clone_streaming(
                text=text,
                language=self.cfg.language,
                ref_audio=self.cfg.ref_audio,
                ref_text=self.cfg.ref_text,
                chunk_size=self.cfg.chunk_size,
                max_new_tokens=self.cfg.max_new_tokens,
                xvec_only=use_xvec,
                temperature=self.cfg.temperature,
                top_k=self.cfg.top_k,
                repetition_penalty=self.cfg.repetition_penalty,
                do_sample=self.cfg.do_sample,
                instruct=eff_instruct,
            )
        return self.model.generate_custom_voice_streaming(
            text=text,
            speaker=self.cfg.speaker,
            language=self.cfg.language,
            instruct=eff_instruct,
            chunk_size=self.cfg.chunk_size,
            max_new_tokens=self.cfg.max_new_tokens,
            temperature=self.cfg.temperature,
            top_k=self.cfg.top_k,
            repetition_penalty=self.cfg.repetition_penalty,
            do_sample=self.cfg.do_sample,
        )

    def stream_timed(
        self,
        text: str,
        stop: threading.Event | None = None,
        instruct: str | None = None,
        *,
        xvec_only: bool | None = None,
    ) -> Iterator[Tuple[np.ndarray, int, dict[str, Any]]]:
        """Yield (float32 mono audio, sample_rate, engine_timing) per chunk."""
        text = text.strip()
        if not text:
            return
        gen = self._generator(text, instruct=instruct, xvec_only=xvec_only)
        first = True
        try:
            for audio_chunk, sr, timing in gen:
                if stop is not None and stop.is_set():
                    break
                self.sr = int(sr)
                timing = dict(timing or {})
                if first and timing:
                    log.info(
                        "tts chunk0 prefill_ms=%.0f decode_ms=%.0f chunk_index=%s",
                        float(timing.get("prefill_ms") or 0),
                        float(timing.get("decode_ms") or 0),
                        timing.get("chunk_index"),
                    )
                    first = False
                yield _to_float32_mono(audio_chunk), int(sr), timing
        finally:
            close = getattr(gen, "close", None)
            if callable(close):
                close()

    def stream(
        self,
        text: str,
        stop: threading.Event | None = None,
        instruct: str | None = None,
        *,
        xvec_only: bool | None = None,
    ) -> Iterator[Tuple[np.ndarray, int]]:
        """Yield (float32 mono audio, sample_rate) chunks as they are generated.

        Stops early (and closes the generator) if `stop` is set, so barge-in cuts
        synthesis mid-sentence instead of finishing the whole reply. `instruct`
        overrides the base voice description for this call only.
        """
        for audio, sr, _timing in self.stream_timed(
            text, stop=stop, instruct=instruct, xvec_only=xvec_only
        ):
            yield audio, sr

    def warmup(self, *, instruct: str | None = None) -> None:
        """One throwaway generation so the first real sentence isn't cold-start slow."""
        try:
            eff = instruct if instruct is not None else self.cfg.instruct or None
            for _ in self.stream("Warming up.", instruct=eff):
                pass
            print("[tts] warmup complete.")
        except Exception as exc:  # noqa: BLE001 - warmup must never crash startup
            print(f"[tts] warmup skipped: {exc}")

    def set_reference(self, ref_audio: str, ref_text: str = "", warm: bool = True) -> None:
        """Switch the cloned voice to a new reference clip at runtime.

        Updates the reference path (and optional transcript) used by every
        subsequent generation. Optionally runs one throwaway generation so the new
        speaker embedding is extracted/cached and the first real reply is fast.
        """
        if not self.clone_capable:
            raise RuntimeError(
                "Voice upload requires clone mode. Restart the server without "
                "VA_TTS_MODE=custom to clone from an uploaded clip."
            )
        self.cfg.ref_audio = ref_audio
        self.cfg.ref_audio = self.cfg.resolve_ref_audio()
        if ref_text.strip():
            self.cfg.ref_text = ref_text.strip()
        else:
            sync_clone_ref_text(self.cfg)
        if not os.path.exists(self.cfg.ref_audio):
            raise FileNotFoundError(self.cfg.ref_audio)
        clear_voice_prompt_cache(self.model)
        self.cfg.mode = "clone"
        self.mode = "clone"
        self.current_ref = self.cfg.ref_audio
        if warm:
            try:
                for _ in self.stream("Okay, I will use this voice now."):
                    pass
            except Exception as exc:  # noqa: BLE001
                print(f"[tts] new-voice warmup skipped: {exc}")

    def list_speakers(self) -> list[str]:
        """Available CustomVoice speaker IDs (only meaningful in custom mode)."""
        try:
            return list(self.model.model.get_supported_speakers() or [])
        except Exception as exc:  # noqa: BLE001
            print(f"[tts] could not list speakers: {exc}")
            return []


def release_tts(tts: Qwen3TTS | NullTTS | None) -> None:
    """Drop TTS weights and free GPU memory before loading a different model."""
    if tts is None:
        return
    model_id = getattr(tts, "model_id", "") or "TTS"
    backend = getattr(tts, "model", None)
    if backend is not None:
        try:
            del tts.model
        except Exception:  # noqa: BLE001
            pass
    try:
        import gc

        gc.collect()
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    except Exception:  # noqa: BLE001
        pass
    log.info("released TTS model %s", model_id)
