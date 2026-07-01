"""Acoustic Echo Cancellation (AEC) for full-duplex voice conversation.

Uses a block Normalized Least Mean Squares (NLMS) adaptive filter to subtract
the speaker output (echo) from the microphone input, so the user can talk while
the AI is speaking without the AI's own voice triggering false barge-ins.

Architecture::

    Speaker output ──┐
                     │  reference signal (downsampled to mic rate)
                     ▼
    Microphone ──► [AEC / NLMS] ──► cleaned signal ──► VAD ──► STT

The player pushes every block it sends to the speakers into a thread-safe FIFO
(``push_reference``).  On the mic side, each raw frame is passed through
``process_frame`` which estimates and subtracts the echo before the frame
reaches the VAD or STT.

The adaptive filter converges in ~1-2 s of active playback and is transparent
(pass-through) whenever nothing is playing.
"""

from __future__ import annotations

import threading
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Reference FIFO — bridges the player (output) thread and the mic (input) thread
# ---------------------------------------------------------------------------

class _ReferenceBuffer:
    """Thread-safe ring buffer that stores speaker output at mic sample rate.

    The player *pushes* blocks as they are sent to the DAC; the AEC *pops*
    blocks of the same length as the mic frames it is processing.  A simple
    overflow / underflow policy keeps the two streams roughly aligned:

    * If the buffer falls behind (more pops than pushes), zeros are returned
      for the missing samples — the filter sees silence and adapts correctly.
    * If the buffer runs ahead (more pushes than pops), old samples are
      discarded so the reference stays temporally close to what the mic is
      picking up.
    """

    def __init__(self, capacity: int) -> None:
        self._buf = np.zeros(capacity, dtype=np.float32)
        self._cap = capacity
        self._r = 0  # read position
        self._w = 0  # write position
        self._lock = threading.Lock()

    # -- called from the player's audio-callback thread --

    def push(self, audio: np.ndarray) -> None:
        with self._lock:
            n = len(audio)
            if n == 0:
                return
            if n >= self._cap:
                audio = audio[-self._cap + 1:]
                n = len(audio)
                self._r = self._w = 0

            avail = (self._w - self._r) % self._cap
            if avail + n >= self._cap:
                skip = avail + n - self._cap + 1
                self._r = (self._r + skip) % self._cap

            end = self._w + n
            if end <= self._cap:
                self._buf[self._w:end] = audio
            else:
                first = self._cap - self._w
                self._buf[self._w:] = audio[:first]
                self._buf[:n - first] = audio[first:]
            self._w = end % self._cap

    # -- called from the mic / AEC processing thread --

    def pop(self, n: int) -> np.ndarray:
        with self._lock:
            avail = (self._w - self._r) % self._cap
            if avail == 0:
                return np.zeros(n, dtype=np.float32)

            # If the player is way ahead, skip old samples to stay aligned.
            if avail > n * 4:
                skip = avail - n
                self._r = (self._r + skip) % self._cap
                avail = n

            take = min(n, avail)
            start = self._r
            end = start + take
            if end <= self._cap:
                out = self._buf[start:end].copy()
            else:
                first = self._cap - start
                out = np.concatenate([self._buf[start:], self._buf[:take - first]])
            self._r = (start + take) % self._cap

            if take < n:
                out = np.concatenate([out, np.zeros(n - take, dtype=np.float32)])
            return out


# ---------------------------------------------------------------------------
# Resampling helper
# ---------------------------------------------------------------------------

def _resample(audio: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    """Linear-interpolation resample (no scipy dependency)."""
    if from_rate == to_rate or len(audio) == 0:
        return audio
    n_out = int(len(audio) * to_rate / from_rate)
    if n_out == 0:
        return np.array([], dtype=audio.dtype)
    x_out = np.linspace(0, len(audio) - 1, n_out)
    return np.interp(x_out, np.arange(len(audio)), audio).astype(audio.dtype)


# ---------------------------------------------------------------------------
# FFT-based convolution (faster than np.convolve for our filter lengths)
# ---------------------------------------------------------------------------

def _fft_convolve(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Full convolution via FFT — O(N log N) instead of O(N^2)."""
    n = len(a) + len(b) - 1
    n_fft = 1 << int(np.ceil(np.log2(n)))
    out = np.fft.irfft(
        np.fft.rfft(a, n_fft) * np.fft.rfft(b, n_fft), n_fft
    )[:n]
    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


# ---------------------------------------------------------------------------
# Echo Canceller
# ---------------------------------------------------------------------------

class EchoCanceller:
    """Block NLMS adaptive filter for acoustic echo cancellation.

    Parameters
    ----------
    filter_ms : int
        Filter length in milliseconds.  Must cover the speaker-to-mic acoustic
        delay plus some room reverb.  150-200 ms is usually sufficient for
        desktop setups (the filter has 16 kHz x 0.15 s = 2400 taps).
    step_size : float
        NLMS step size (mu).  Larger = faster convergence but more noise during
        double-talk.  0.15-0.3 is a safe range.
    mic_rate : int
        Sample rate of the microphone input (and the rate the filter operates
        at).  The reference signal is resampled to this rate internally.
    """

    def __init__(
        self,
        filter_ms: int = 150,
        step_size: float = 0.25,
        mic_rate: int = 16000,
    ) -> None:
        self.mic_rate = mic_rate
        self.L = max(16, int(mic_rate * filter_ms / 1000))
        self.mu = step_size

        # Adaptive filter coefficients.
        self.w = np.zeros(self.L, dtype=np.float64)

        # Sliding reference window — always holds exactly L + current-frame
        # samples so the Toeplitz-like convolution covers the full filter span.
        self._ref_window = np.zeros(self.L, dtype=np.float64)

        # FIFO fed by the player's audio callback.
        self._ref_buf = _ReferenceBuffer(mic_rate * 3)   # 3 s capacity

    def reset(self) -> None:
        """Zero the adaptive filter (call after divergence or a bad false barge-in)."""
        self.w.fill(0.0)
        self._ref_window.fill(0.0)
        with self._ref_buf._lock:
            self._ref_buf._buf.fill(0.0)
            self._ref_buf._r = 0
            self._ref_buf._w = 0

    # -- Player side (called from the audio-callback thread) -----------------

    def push_reference(self, audio_f32: np.ndarray, sample_rate: int) -> None:
        """Feed speaker output into the reference buffer.

        The player calls this from its audio callback with the *post-EQ,
        post-gain* block — i.e. exactly what goes to the speakers.
        """
        mono = audio_f32.ravel() if audio_f32.ndim > 1 else audio_f32
        if sample_rate != self.mic_rate:
            mono = _resample(mono, sample_rate, self.mic_rate)
        self._ref_buf.push(mono.astype(np.float32))

    # -- Mic side (called from the recording / VAD thread) -------------------

    def process_frame(self, mic_int16: np.ndarray) -> np.ndarray:
        """Cancel echo from one mic frame.

        Parameters
        ----------
        mic_int16 : np.ndarray
            Raw microphone frame as int16 mono.

        Returns
        -------
        np.ndarray
            Echo-cancelled frame, same dtype (int16) and length.
        """
        F = len(mic_int16)
        mic = np.clip(mic_int16.astype(np.float64) / 32768.0, -1.0, 1.0)

        # Pop the corresponding reference samples.
        ref = np.clip(self._ref_buf.pop(F).astype(np.float64), -1.0, 1.0)

        if not np.isfinite(self.w).all():
            self.reset()
            return mic_int16

        # Build the extended reference: [history(L) | current(F)] = L+F samples.
        ref_ext = np.concatenate([self._ref_window, ref])

        # --- Echo estimate via FFT convolution --------------------------------
        echo_full = _fft_convolve(ref_ext, self.w)
        echo = echo_full[self.L: self.L + F]

        # Residual (cleaned mic signal).
        error = np.clip(mic - echo, -1.0, 1.0)
        error = np.nan_to_num(error, nan=0.0, posinf=0.0, neginf=0.0)

        # --- Double-talk detection --------------------------------------------
        ref_pow = float(np.mean(ref ** 2))
        mic_pow = float(np.mean(mic ** 2))

        # User louder than the echo — pass mic through so VAD/STT hear them.
        if ref_pow >= 1e-10 and mic_pow > 1.35 * ref_pow:
            self._ref_window = ref_ext[-self.L:].copy()
            out = np.clip(mic * 32768.0, -32768, 32767)
            return np.nan_to_num(out, nan=0.0, posinf=32767.0, neginf=-32768.0).astype(np.int16)

        if ref_pow < 1e-10:
            mu = 0.0
        elif mic_pow > 4.0 * ref_pow:
            mu = self.mu * 0.02
        else:
            mu = self.mu

        # --- Block NLMS filter update -----------------------------------------
        if mu > 0.0:
            grad_full = _fft_convolve(ref_ext, error[::-1])
            gradient = grad_full[F: F + self.L][::-1]
            gradient = np.nan_to_num(gradient, nan=0.0, posinf=0.0, neginf=0.0)

            ref_power = float(np.sum(ref_ext ** 2)) + 1e-8
            self.w += mu * gradient / ref_power
            np.clip(self.w, -5.0, 5.0, out=self.w)

            if not np.isfinite(self.w).all():
                self.reset()
                return mic_int16

        # Update the sliding reference history (last L samples).
        self._ref_window = ref_ext[-self.L:].copy()

        out = np.clip(error * 32768.0, -32768, 32767)
        return np.nan_to_num(out, nan=0.0, posinf=32767.0, neginf=-32768.0).astype(np.int16)
