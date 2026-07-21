"""Tests for the system/bash tools and the broadened tool-routing predicate."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from tools.system_tools import (
    build_system_tools,
    get_air_quality,
    get_current_datetime,
    run_bash,
)


def test_get_current_datetime_shape():
    dt = get_current_datetime()
    assert dt["weekday"] in {
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    }
    assert dt["date"] and dt["iso"] and dt["spoken"]
    assert dt["weekday"] in dt["spoken"]


def test_run_bash_allowed_command_runs():
    out = run_bash("date")
    assert out["exit_code"] == 0
    assert out["output"]


@pytest.mark.parametrize("cmd", ["uname -a", "df -h", "free -h", "hostname -s"])
def test_run_bash_allowed_read_only_arguments(cmd):
    out = run_bash(cmd)
    assert out["exit_code"] == 0
    assert out["output"]


@pytest.mark.parametrize("cmd", ["date; rm -rf /", "uptime | mail x", "echo $HOME", "date && whoami"])
def test_run_bash_rejects_metacharacters(cmd):
    out = run_bash(cmd)
    assert "error" in out
    assert "disallowed characters" in out["error"]


def test_run_bash_rejects_non_allowlisted():
    out = run_bash("cat /etc/passwd")
    assert out["error"].startswith("command 'cat' is not allowed")
    assert "date" in out["allowed"]


@pytest.mark.parametrize(
    "cmd",
    ["date -s 2030-01-01", "hostname new-hostname", "df /etc", "whoami --help"],
)
def test_run_bash_rejects_mutating_or_unapproved_arguments(cmd):
    out = run_bash(cmd)
    assert "error" in out
    assert "arguments are not allowed" in out["error"]


def test_run_bash_empty():
    assert "error" in run_bash("")


def test_get_air_quality_parses_mocked_payload():
    geocode = json.dumps({"results": [
        {"name": "Seattle", "country_code": "US", "latitude": 47.6, "longitude": -122.3},
    ]})
    air = json.dumps({"current": {"us_aqi": 42, "pm2_5": 8.1, "pm10": 12.0, "ozone": 30}})
    with patch("tools.system_tools._http_get", side_effect=[geocode, air]):
        out = get_air_quality("Seattle")
    assert out["us_aqi"] == 42
    assert out["category"] == "good"
    assert "Seattle" in out["location"]
    assert "good" in out["spoken"]


def test_build_system_tools_registers_three():
    specs = {s.name for s in build_system_tools()}
    assert specs == {"get_current_datetime", "get_air_quality", "run_bash"}


@pytest.mark.parametrize("text", [
    "what time is it?",
    "what day is it",
    "air quality today",
    "what's the temperature tonight",
    "how is the weather",
    "when does the sun set",
])
def test_should_consider_tools_true_for_factual(text):
    from agent import VoiceAgent
    assert VoiceAgent._should_consider_tools(text) is True


@pytest.mark.parametrize("text", ["hi maya", "i love you maya", "you're the best", "mmm okay"])
def test_should_consider_tools_false_for_casual(text):
    from agent import VoiceAgent
    assert VoiceAgent._should_consider_tools(text) is False


def test_dspy_router_module_imports_without_dspy():
    # The module must import even when `dspy` is not installed (lazy import).
    import dspy_router  # noqa: F401

    # Constructing the router without dspy installed should raise a clear error
    # that the agent catches — not import at module load.
    try:
        import dspy  # noqa: F401
    except ImportError:
        with pytest.raises(ImportError):
            dspy_router.DspyRouter()
