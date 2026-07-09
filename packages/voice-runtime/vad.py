"""Voice-activity detection for turn-taking and full-duplex barge-in.

SharedMic keeps one device stream open for the session and delivers **raw**
frames. AEC is applied per consumer (idle listen + barge STT), never in the
capture callback.
"""

from __future__ import annotations

import collections
import queue
import threading
from typing import Callable, Optional

import numpy as np

from config import CONFIG, VADConfig


class _VADState:
    def __init__(self, cfg: VADConfig, sample_rate: int):
        import webrtcvad

        if cfg.frame_ms not in (10, 20, 30):
            raise ValueError("VAD frame_ms must be 10, 20, or 30")
        self.cfg = cfg
        self.sample_rate = sample_rate
        self.vad = webrtcvad.Vad(cfg.aggressiveness)
        self.frame_bytes = int(sample_rate * (cfg.frame_ms / 1000.0)) * 2

    def is_speech(self, frame_bytes: bytes) -> bool:
        if len(frame_bytes) != self.frame_bytes:
            return False
        return self.vad.is_speech(frame_bytes, self.sample_rate)


class SharedMic:
    """Persistent raw-mic input for full-duplex sessions."""

    def __init__(
        self,
        sample_rate: int | None = None,
        frame_ms: int | None = None,
    ):
        cfg = CONFIG.vad
        self.sample_rate = sample_rate or CONFIG.stt.sample_rate
        self.frame_ms = frame_ms or cfg.frame_ms
        self._frame_samples = int(self.sample_rate * self.frame_ms / 1000)
        self._q: queue.Queue[np.ndarray] = queue.Queue(maxsize=512)
        self._stream = None
        self._stopped = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> None:
        from player import load_sounddevice

        sd = load_sounddevice()

        if self._stream is not None:
            return
        self._stopped.clear()

        def callback(indata, _frames, _time, _status) -> None:
            if self._stopped.is_set():
                return
            frame = np.asarray(indata, dtype=np.int16).reshape(-1).copy()
            try:
                self._q.put_nowait(frame)
            except queue.Full:
                try:
                    self._q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._q.put_nowait(frame)
                except queue.Full:
                    pass

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self._frame_samples,
            callback=callback,
        )
        self._stream.start()

    def stop(self) -> None:
        self._stopped.set()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001
                pass
            self._stream = None
        self.flush()

    def flush(self) -> None:
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break

    def read_frame(self, should_stop: Optional[Callable[[], bool]] = None) -> Optional[np.ndarray]:
        stop = should_stop or (lambda: False)
        while not stop() and not self._stopped.is_set():
            try:
                return self._q.get(timeout=0.05)
            except queue.Empty:
                continue
        return None

    def capture_lock(self):
        return _MicCaptureLock(self._lock)


class _MicCaptureLock:
    def __init__(self, lock: threading.Lock):
        self._lock = lock

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, *exc):
        self._lock.release()


def _frame_rms(frame: np.ndarray) -> float:
    if frame.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))


def audio_rms(audio: np.ndarray) -> float:
    return _frame_rms(np.asarray(audio, dtype=np.int16).reshape(-1))


def audio_peak(audio: np.ndarray) -> int:
    if audio.size == 0:
        return 0
    return int(np.max(np.abs(np.asarray(audio, dtype=np.int32).reshape(-1))))


def is_plausible_user_speech(
    audio: np.ndarray,
    playback_level: Optional[Callable[[], float]] = None,
    min_rms: float = 520.0,
    min_peak: int = 2400,
) -> bool:
    """Reject silence, muted-mic noise, and weak speaker bleed before STT."""
    if audio.size == 0:
        return False
    rms = audio_rms(audio)
    peak = audio_peak(audio)
    if rms < min_rms or peak < min_peak:
        return False
    playing = playback_level() if playback_level is not None else 0.0
    if playing > 0.008:
        bleed = max(min_rms, playing * 11000.0)
        if rms < bleed * 2.0:
            return False
    return True


def _capture_utterance(
    state: _VADState,
    frame_samples: int,
    read_frame: Callable[[], Optional[np.ndarray]],
    should_stop: Optional[Callable[[], bool]],
    on_speech_start: Optional[Callable[[], None]],
    cfg: VADConfig,
    timeout_seconds: float = -1.0,
) -> np.ndarray:
    import time

    silence_frames_needed = max(1, cfg.silence_ms // cfg.frame_ms)
    min_speech_frames = max(1, cfg.min_speech_ms // cfg.frame_ms)
    max_frames = max(1, cfg.max_turn_ms // cfg.frame_ms)

    ring = collections.deque(maxlen=10)
    voiced: list[np.ndarray] = []
    triggered = False
    silence_run = 0
    total_frames = 0
    speech_frames = 0
    stop = should_stop or (lambda: False)
    start_time = time.monotonic()

    while total_frames < max_frames:
        if stop():
            return np.array([], dtype=np.int16)
        if timeout_seconds > 0.0 and not triggered:
            if time.monotonic() - start_time > timeout_seconds:
                return np.array([], dtype=np.int16)
        frame = read_frame()
        if frame is None:
            if stop():
                return np.array([], dtype=np.int16)
            continue
        if frame.shape[0] != frame_samples:
            continue
        total_frames += 1
        speech = state.is_speech(frame.tobytes())

        if not triggered:
            ring.append(frame)
            if speech:
                triggered = True
                if on_speech_start:
                    on_speech_start()
                voiced.extend(ring)
                ring.clear()
        else:
            voiced.append(frame)
            if speech:
                speech_frames += 1
                silence_run = 0
            else:
                silence_run += 1
                if silence_run >= silence_frames_needed:
                    break

    if not triggered or speech_frames < min_speech_frames:
        return np.array([], dtype=np.int16)
    return np.concatenate(voiced) if voiced else np.array([], dtype=np.int16)


def record_barge_utterance(
    mic: SharedMic,
    cfg: VADConfig,
    is_trigger: Callable[[np.ndarray], bool],
    should_stop: Callable[[], bool],
    on_speech_start: Optional[Callable[[], None]] = None,
    trigger_frames: int = 4,
    silence_rms: float = 300.0,
    frame_processor: Optional[Callable[[np.ndarray], np.ndarray]] = None,
) -> np.ndarray:
    """Capture a user interruption while the agent may be playing.

    Trigger on sustained ``is_trigger`` hits. After trigger, record every frame
    until raw RMS stays below ``silence_rms``. End-of-turn uses energy only so
    AEC/VAD cannot discard the utterance mid-capture. Returns STT-ready audio
    (AEC-cleaned when ``frame_processor`` is set).
    """
    state = _VADState(cfg, mic.sample_rate)
    frame_samples = state.frame_bytes // 2
    silence_frames_needed = max(1, cfg.silence_ms // cfg.frame_ms)
    min_samples = max(frame_samples * 2, int(mic.sample_rate * cfg.min_speech_ms / 1000))
    max_frames = max(1, cfg.max_turn_ms // cfg.frame_ms)
    trigger_frames = max(1, trigger_frames)

    ring: collections.deque[np.ndarray] = collections.deque(maxlen=12)
    voiced: list[np.ndarray] = []
    pre_trigger = 0
    triggered = False
    silence_run = 0
    total = 0

    while total < max_frames and not should_stop():
        raw = mic.read_frame(should_stop)
        if raw is None or raw.shape[0] != frame_samples:
            continue
        total += 1

        if not triggered:
            ring.append(raw)
            if is_trigger(raw):
                pre_trigger += 1
                if pre_trigger >= trigger_frames:
                    triggered = True
                    if on_speech_start:
                        on_speech_start()
                    for f in ring:
                        voiced.append(frame_processor(f) if frame_processor else f)
                    ring.clear()
            else:
                pre_trigger = 0
            continue

        voiced.append(frame_processor(raw) if frame_processor else raw)
        if _frame_rms(raw) < silence_rms:
            silence_run += 1
            if silence_run >= silence_frames_needed:
                break
        else:
            silence_run = 0

    if not triggered:
        return np.array([], dtype=np.int16)
    audio = np.concatenate(voiced) if voiced else np.array([], dtype=np.int16)
    if audio.size < min_samples:
        return np.array([], dtype=np.int16)
    return audio


def record_until_silence(
    cfg: VADConfig | None = None,
    sample_rate: int | None = None,
    on_speech_start: Optional[Callable[[], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    aec=None,
    mic: SharedMic | None = None,
    frame_processor: Optional[Callable[[np.ndarray], np.ndarray]] = None,
    timeout_seconds: float = -1.0,
) -> np.ndarray:
    cfg = cfg or CONFIG.vad
    sr = sample_rate or CONFIG.stt.sample_rate
    state = _VADState(cfg, sr)
    frame_samples = state.frame_bytes // 2

    def _process(frame: np.ndarray) -> np.ndarray:
        if frame_processor is not None:
            return frame_processor(frame)
        if aec is not None:
            return aec.process_frame(frame)
        return frame

    if mic is not None:
        def read_shared() -> Optional[np.ndarray]:
            raw = mic.read_frame(should_stop)
            return _process(raw) if raw is not None else None

        return _capture_utterance(
            state, frame_samples, read_shared, should_stop, on_speech_start, cfg, timeout_seconds
        )

    import sounddevice as sd

    with sd.InputStream(samplerate=sr, channels=1, dtype="int16", blocksize=frame_samples) as stream:
        def read_ephemeral() -> Optional[np.ndarray]:
            if should_stop is not None and should_stop():
                return None
            block, _overflowed = stream.read(frame_samples)
            frame = np.asarray(block, dtype=np.int16).reshape(-1)
            return _process(frame)

        return _capture_utterance(
            state, frame_samples, read_ephemeral, should_stop, on_speech_start, cfg, timeout_seconds
        )


def barge_speech_detector(
    state: _VADState,
    playback_level: Optional[Callable[[], float]] = None,
    rms_floor: int = 680,
):
    """Trigger for barge-in. During playback, require mic energy above bleed."""

    def _detect(frame: np.ndarray) -> bool:
        rms = _frame_rms(frame)
        playing = playback_level() if playback_level is not None else 0.0
        if playing > 0.008:
            needed = max(rms_floor, int(playing * 12000))
            if rms < needed:
                return False
            if rms >= needed * 1.4:
                return True
            return state.is_speech(frame.tobytes()) and rms >= needed * 1.05
        if state.is_speech(frame.tobytes()):
            return True
        return rms >= rms_floor

    return _detect


class BargeInMonitor:
    """Instant barge-in: stop playback as soon as sustained speech is detected."""

    def __init__(
        self,
        on_barge_in: Callable[[], None],
        cfg: VADConfig | None = None,
        sample_rate: int | None = None,
        trigger_frames: int = 3,
        aec=None,
        mic: SharedMic | None = None,
    ):
        self.cfg = cfg or CONFIG.vad
        self.sr = sample_rate or CONFIG.stt.sample_rate
        self.on_barge_in = on_barge_in
        self.trigger_frames = trigger_frames
        self.aec = aec
        self.mic = mic
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _run(self) -> None:
        state = _VADState(self.cfg, self.sr)
        frame_samples = state.frame_bytes // 2
        consecutive = 0

        def _process(frame: np.ndarray) -> np.ndarray:
            return self.aec.process_frame(frame) if self.aec is not None else frame

        if self.mic is not None:
            with self.mic.capture_lock():
                while not self._stop.is_set():
                    raw = self.mic.read_frame(self._stop.is_set)
                    if raw is None or raw.shape[0] != frame_samples:
                        continue
                    frame = _process(raw)
                    if state.is_speech(frame.tobytes()):
                        consecutive += 1
                        if consecutive >= self.trigger_frames:
                            self.on_barge_in()
                            return
                    else:
                        consecutive = 0
            return

        import sounddevice as sd

        try:
            with sd.InputStream(
                samplerate=self.sr, channels=1, dtype="int16", blocksize=frame_samples
            ) as stream:
                while not self._stop.is_set():
                    block, _ = stream.read(frame_samples)
                    frame = np.asarray(block, dtype=np.int16).reshape(-1)
                    if frame.shape[0] != frame_samples:
                        continue
                    frame = _process(frame)
                    if state.is_speech(frame.tobytes()):
                        consecutive += 1
                        if consecutive >= self.trigger_frames:
                            self.on_barge_in()
                            return
                    else:
                        consecutive = 0
        except Exception as exc:  # noqa: BLE001
            print(f"[vad] barge-in monitor stopped: {exc}")


def record_fixed(seconds: float, sample_rate: int | None = None) -> np.ndarray:
    import sounddevice as sd

    sr = sample_rate or CONFIG.stt.sample_rate
    frames = int(seconds * sr)
    audio = sd.rec(frames, samplerate=sr, channels=1, dtype="int16")
    sd.wait()
    return audio.reshape(-1)
