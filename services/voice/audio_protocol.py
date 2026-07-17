"""Browser mic audio protocol negotiation and framed PCM (AUDIO-001)."""

from __future__ import annotations

import struct
from dataclasses import dataclass

PROTOCOL_VERSION = 1
FRAME_MAGIC = 0x4159414D  # 'MAYA' little-endian
FRAME_HEADER_SIZE = 16
MAX_PCM_BYTES = 48_000  # ~0.5s of 48 kHz mono s16le
MAX_RAW_FRAME_BYTES = FRAME_HEADER_SIZE + MAX_PCM_BYTES
SUPPORTED_SAMPLE_RATES = frozenset({16000, 22050, 24000, 32000, 44100, 48000})
TARGET_INGRESS_RATE = 48000
SUPPORTED_FORMATS = frozenset({"s16le"})


@dataclass(frozen=True)
class AudioNegotiated:
    protocol: int
    format: str
    sample_rate: int
    channels: int
    frames_per_chunk: int
    session_id: str | None = None
    generation_id: int | None = None


@dataclass
class FrameStreamState:
    last_sequence: int | None = None
    last_sample_index: int | None = None
    gap_count: int = 0
    drop_count: int = 0


class AudioProtocolError(ValueError):
    pass


def audio_challenge_payload(*, connection_id: str, session_id: str | None = None) -> dict:
    return {
        "type": "audio_challenge",
        "protocol": PROTOCOL_VERSION,
        "formats": sorted(SUPPORTED_FORMATS),
        "sample_rates": sorted(SUPPORTED_SAMPLE_RATES),
        "channels": [1],
        "max_pcm_bytes": MAX_PCM_BYTES,
        "frame_header_bytes": FRAME_HEADER_SIZE,
        "connection_id": connection_id,
        "session_id": session_id,
    }


def negotiate_audio_hello(event: dict) -> AudioNegotiated:
    if not isinstance(event, dict) or event.get("type") != "audio_hello":
        raise AudioProtocolError("expected audio_hello")
    protocol = int(event.get("protocol") or 0)
    if protocol != PROTOCOL_VERSION:
        raise AudioProtocolError(f"unsupported protocol {protocol}")
    fmt = str(event.get("format") or "").strip().lower()
    if fmt not in SUPPORTED_FORMATS:
        raise AudioProtocolError(f"unsupported format {fmt}")
    sample_rate = int(event.get("sample_rate") or 0)
    if sample_rate not in SUPPORTED_SAMPLE_RATES:
        raise AudioProtocolError(f"unsupported sample_rate {sample_rate}")
    channels = int(event.get("channels") or 0)
    if channels != 1:
        raise AudioProtocolError("only mono (channels=1) is supported")
    frames = int(event.get("frames_per_chunk") or 0)
    if frames < 128 or frames > 8192:
        raise AudioProtocolError("frames_per_chunk out of range")
    gen = event.get("generation_id")
    return AudioNegotiated(
        protocol=protocol,
        format=fmt,
        sample_rate=sample_rate,
        channels=channels,
        frames_per_chunk=frames,
        session_id=str(event.get("session_id") or "") or None,
        generation_id=int(gen) if isinstance(gen, int) else None,
    )


def pack_pcm_frame(
    pcm: bytes,
    *,
    sequence: int,
    sample_index: int,
    flags: int = 0,
) -> bytes:
    if len(pcm) % 2 != 0:
        raise AudioProtocolError("pcm must be even-sized s16le")
    if len(pcm) > MAX_PCM_BYTES:
        raise AudioProtocolError("pcm frame too large")
    header = struct.pack(
        "<IBBHII",
        FRAME_MAGIC,
        PROTOCOL_VERSION,
        flags & 0xFF,
        0,
        int(sequence) & 0xFFFFFFFF,
        int(sample_index) & 0xFFFFFFFF,
    )
    return header + pcm


def unpack_pcm_frame(raw: bytes, state: FrameStreamState | None = None) -> tuple[bytes, int, int, int]:
    """Return (pcm, sequence, sample_index, flags). Raises AudioProtocolError on bad frames."""
    if len(raw) < FRAME_HEADER_SIZE:
        raise AudioProtocolError("frame too short")
    magic, version, flags, _reserved, sequence, sample_index = struct.unpack_from(
        "<IBBHII", raw, 0
    )
    if magic != FRAME_MAGIC:
        raise AudioProtocolError("bad frame magic")
    if version != PROTOCOL_VERSION:
        raise AudioProtocolError(f"bad frame version {version}")
    pcm = raw[FRAME_HEADER_SIZE:]
    if len(pcm) % 2 != 0:
        raise AudioProtocolError("odd pcm byte length")
    if len(pcm) > MAX_PCM_BYTES:
        raise AudioProtocolError("pcm frame too large")
    if not pcm:
        raise AudioProtocolError("empty pcm payload")
    if state is not None:
        if state.last_sequence is not None:
            expected = (state.last_sequence + 1) & 0xFFFFFFFF
            if sequence != expected:
                state.gap_count += 1
                if sequence < expected and sequence != 0:
                    state.drop_count += 1
                raise AudioProtocolError(
                    f"sequence gap {sequence} (expected {expected})"
                )
        if state.last_sample_index is not None and sample_index < state.last_sample_index:
            state.gap_count += 1
            raise AudioProtocolError("non-monotonic sample_index")
        state.last_sequence = sequence
        state.last_sample_index = sample_index
    return pcm, sequence, sample_index, flags


def resample_s16le_mono(pcm: bytes, src_rate: int, dst_rate: int = TARGET_INGRESS_RATE) -> bytes:
    """Resample mono s16le to dst_rate (torchaudio / anti-aliased)."""
    from services.voice.resample import resample_s16le_mono as _resample

    return _resample(pcm, src_rate, dst_rate)
