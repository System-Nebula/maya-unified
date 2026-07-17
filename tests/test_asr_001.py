"""ASR-001: Whisper default, dedicated ASR port, health probe messaging."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from stt import (
    DEFAULT_ASR_PORT,
    VTS_COLLISION_PORT,
    asr_health_url,
    asr_service_root,
    create_stt,
    probe_qwen3_asr,
)


def test_default_asr_port_avoids_vts() -> None:
    assert DEFAULT_ASR_PORT == 8091
    assert DEFAULT_ASR_PORT != VTS_COLLISION_PORT


def test_asr_health_url_strips_v1() -> None:
    assert asr_service_root("http://127.0.0.1:8091/v1") == "http://127.0.0.1:8091"
    assert asr_health_url("http://127.0.0.1:8091/v1") == "http://127.0.0.1:8091/health"


def test_probe_qwen_unavailable_is_actionable() -> None:
    cfg = SimpleNamespace(
        asr_base_url="http://127.0.0.1:65530/v1",
        asr_model="Qwen/Qwen3-ASR-0.6B",
    )
    health = probe_qwen3_asr(cfg, timeout_s=0.2)  # type: ignore[arg-type]
    assert health["ok"] is False
    detail = health["detail"] or ""
    assert "requirements-asr.txt" in detail or "start-asr" in detail
    assert "whisper" in detail.lower()


def test_create_stt_qwen_fails_without_fallback() -> None:
    cfg = SimpleNamespace(
        backend="qwen3-asr",
        asr_base_url="http://127.0.0.1:65530/v1",
        asr_model="Qwen/Qwen3-ASR-0.6B",
        language="en",
        sample_rate=16000,
        whisper_model="tiny.en",
        whisper_compute_type="int8",
        device="cpu",
        asr_fallback_whisper=False,
    )
    with pytest.raises(RuntimeError, match="start-asr|requirements-asr|whisper"):
        create_stt(cfg)  # type: ignore[arg-type]


def test_start_asr_script_has_no_pip_upgrade() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "start-asr.ps1").read_text(encoding="utf-8")
    assert "pip install -U qwen-asr" not in script
    assert "python -m pip install -U qwen-asr" not in script
    assert ".venv-asr" in script
    assert "requirements-asr.txt" in script
    assert "8091" in script


def test_requirements_asr_pins_qwen() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "scripts" / "requirements-asr.txt").read_text(encoding="utf-8")
    assert "qwen-asr==0.0.6" in text
    # Pin file must not instruct unpinned upgrades as the install path.
    assert not any(
        line.strip().startswith("pip install -U") for line in text.splitlines()
    )


def test_settings_schema_defaults_whisper() -> None:
    from services.settings.schema import DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS["dictation"]["backend"] == "whisper"
    assert "8091" in DEFAULT_SETTINGS["dictation"]["asr_base_url"]


def test_config_module_default_strings() -> None:
    """Source defaults must prefer Whisper + 8091 (env may override at runtime)."""
    root = Path(__file__).resolve().parents[1]
    text = (root / "packages" / "voice-runtime" / "config.py").read_text(encoding="utf-8")
    assert '_env_str("VA_STT_BACKEND", "whisper")' in text
    assert "8091" in text
    assert 'VA_ASR_BASE_URL", "http://127.0.0.1:8091/v1"' in text
