"""Tests for reference transcript sync."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "voice-runtime"))

from ref_text import ensure_ref_text_sidecar, read_ref_text_sidecar, sync_clone_ref_text  # noqa: E402


@dataclass
class _Cfg:
    ref_audio: str = ""
    ref_text: str = ""


def test_sync_clears_stale_and_loads_sidecar(tmp_path: Path) -> None:
    wav = tmp_path / "voice.wav"
    wav.write_bytes(b"RIFF")
    sidecar = tmp_path / "voice.txt"
    sidecar.write_text("hello from sidecar", encoding="utf-8")

    cfg = _Cfg(ref_audio=str(wav), ref_text="stale transcript from old voice")
    sync_clone_ref_text(cfg)
    assert cfg.ref_text == "hello from sidecar"


def test_sync_empty_when_no_sidecar(tmp_path: Path) -> None:
    wav = tmp_path / "new.wav"
    wav.write_bytes(b"RIFF")
    cfg = _Cfg(ref_audio=str(wav), ref_text="old")
    sync_clone_ref_text(cfg)
    assert cfg.ref_text == ""


def test_explicit_override_wins(tmp_path: Path) -> None:
    wav = tmp_path / "voice.wav"
    wav.write_bytes(b"RIFF")
    (tmp_path / "voice.txt").write_text("sidecar", encoding="utf-8")
    cfg = _Cfg(ref_audio=str(wav))
    sync_clone_ref_text(cfg, explicit="manual transcript")
    assert cfg.ref_text == "manual transcript"


def test_read_sidecar(tmp_path: Path) -> None:
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    assert read_ref_text_sidecar(str(wav)) == ""
    (tmp_path / "a.txt").write_text("  trimmed  \n", encoding="utf-8")
    assert read_ref_text_sidecar(str(wav)) == "trimmed"


def test_ensure_ref_text_sidecar_writes_transcript(tmp_path: Path) -> None:
    wav = tmp_path / "pj.wav"
    wav.write_bytes(b"RIFF")
    assert ensure_ref_text_sidecar(str(wav), transcribe=lambda _p: "hello pj") == "hello pj"
    assert (tmp_path / "pj.txt").read_text(encoding="utf-8") == "hello pj"
    assert ensure_ref_text_sidecar(str(wav), transcribe=lambda _p: "ignored") == "hello pj"
