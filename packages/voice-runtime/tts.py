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

import os
import threading
from typing import Iterator, Tuple

import numpy as np

from config import CONFIG, TTSConfig


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

    def _generator(self, text: str, instruct: str | None = None):
        """Return the underlying faster-qwen3-tts streaming generator for `text`.

        `instruct` overrides the configured base description for this call (used by
        per-reply auto-delivery); pass None to fall back to `cfg.instruct`.
        """
        self._seed()
        eff_instruct = (instruct if instruct is not None else self.cfg.instruct) or None
        if self.mode == "clone":
            return self.model.generate_voice_clone_streaming(
                text=text,
                language=self.cfg.language,
                ref_audio=self.cfg.ref_audio,
                ref_text=self.cfg.ref_text,
                chunk_size=self.cfg.chunk_size,
                max_new_tokens=self.cfg.max_new_tokens,
                xvec_only=self.cfg.xvec_only,
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

    def stream(
        self, text: str, stop: threading.Event | None = None, instruct: str | None = None
    ) -> Iterator[Tuple[np.ndarray, int]]:
        """Yield (float32 mono audio, sample_rate) chunks as they are generated.

        Stops early (and closes the generator) if `stop` is set, so barge-in cuts
        synthesis mid-sentence instead of finishing the whole reply. `instruct`
        overrides the base voice description for this call only.
        """
        text = text.strip()
        if not text:
            return
        gen = self._generator(text, instruct=instruct)
        try:
            for audio_chunk, sr, _timing in gen:
                if stop is not None and stop.is_set():
                    break
                self.sr = int(sr)
                yield _to_float32_mono(audio_chunk), int(sr)
        finally:
            close = getattr(gen, "close", None)
            if callable(close):
                close()

    def warmup(self) -> None:
        """One throwaway generation so the first real sentence isn't cold-start slow."""
        try:
            for _ in self.stream("Warming up."):
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
        if not os.path.exists(ref_audio):
            raise FileNotFoundError(ref_audio)
        self.cfg.mode = "clone"
        self.mode = "clone"
        self.cfg.ref_audio = ref_audio
        self.cfg.ref_text = ref_text or ""
        self.current_ref = ref_audio
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
