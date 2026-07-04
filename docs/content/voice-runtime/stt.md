---
title: STT Pipeline
tags: [voice-runtime, stt]
source: packages/voice-runtime/stt.py
---

# STT Pipeline

Speech-to-text in Maya uses **[faster-whisper](https://github.com/SYSTRAN/faster-whisper)**—a CTranslate2 implementation of OpenAI Whisper that runs efficiently on NVIDIA GPUs (and CPU with reduced precision).

The public surface is small: **`WhisperSTT.transcribe_array(int16_audio, sample_rate)`** returns plain text for the agent turn loop. All mic modes (push-to-talk, VAD) converge on this method.

## Class: `WhisperSTT`

Construction (`stt.py`):

```python
WhisperModel(
    cfg.whisper_model,
    device=device,           # cuda or cpu from VA_STT_DEVICE
    compute_type=compute_type,  # float16 on GPU, int8 fallback on CPU
)
```

### Configuration defaults (`STTConfig`)

| Env var | Default | Notes |
|---------|---------|-------|
| `VA_WHISPER_MODEL` | `small.en` | Also: `tiny.en`, `base.en`, `medium.en`, `large-v3` |
| `VA_WHISPER_COMPUTE` | `float16` | Use `int8` on CPU |
| `VA_STT_DEVICE` | `cuda` | Set `cpu` if no GPU |
| `VA_STT_LANGUAGE` | `en` | Empty → auto-detect |
| `VA_STT_SAMPLE_RATE` | `16000` | Must match mic capture rate |

**Tradeoff:** larger models = better accuracy + higher latency and VRAM. `small.en` is the default balance for interactive voice.

## Transcription paths

### `transcribe_array`

1. Normalize input to int16 mono numpy array
2. Write temporary WAV via `_write_temp_wav`
3. Call `transcribe_file`
4. Delete temp file

Used for normal turns and barge-in passes.

### `transcribe_file`

Core faster-whisper invocation:

```python
segments, _info = self.model.transcribe(path, **kwargs)
return " ".join(seg.text.strip() for seg in segments).strip()
```

**Normal turn kwargs:**

- `language` from config
- `beam_size=1` — greedy decode for speed

**Barge-in kwargs** (`barge=True`):

- `vad_filter=True`
- Stricter thresholds:
  - `no_speech_threshold=0.62`
  - `log_prob_threshold=-0.45`
  - `compression_ratio_threshold=2.2`
  - `condition_on_previous_text=False`

Barge STT must avoid false triggers from TTS bleed-through; stricter filtering reduces accidental cancellation from echo.

## GPU sharing with TTS

Whisper and Qwen3-TTS compete for CUDA memory. Unified mode serializes heavy inference via **`services/voice/inference.INFERENCE_LOCK`** so STT and TTS don't run concurrent GPU peaks.

Symptom: turn latency spikes when TTS was just active—expected under lock contention.

## Audio format expectations

- **Sample rate:** 16 kHz typical (WebRTC / browser capture)
- **Channels:** mono int16 PCM
- Browser dashboard resamples before upload; local `SharedMic` uses `CONFIG.vad.frame_ms` frames

## Failure modes

| Symptom | Diagnosis |
|---------|-----------|
| Empty transcript | Silence detected, barge thresholds too strict, or wrong language |
| Garbage text | Room noise — tune VAD aggressiveness, use better mic |
| CUDA OOM on STT | Model too large — try `tiny.en` or free VRAM from TTS |
| Slow first transcript | Cold model load — first run downloads weights |

## Tuning for your hardware

| Profile | Suggested `VA_WHISPER_MODEL` |
|---------|------------------------------|
| RTX 4090 / low latency | `small.en` or `medium.en` |
| 8 GB VRAM shared with TTS | `tiny.en` or `base.en` |
| CPU-only dev | `tiny.en`, `VA_STT_DEVICE=cpu`, `VA_WHISPER_COMPUTE=int8` |

## Related

- [[Voice Runtime/VAD and Barge-in]] — when STT is invoked
- [[Voice Runtime/Agent Orchestrator]] — consumes STT output
- [[Architecture/Request Pipeline]]
