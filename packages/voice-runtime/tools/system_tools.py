"""System/bash tools: current date-time, air quality, and a guarded shell runner.

These answer the everyday factual questions a voice companion is expected to
handle ("what day is it?", "what's the air quality?") which otherwise fall
through to persona chat and get deflected. All keyless.

`run_bash` is deliberately conservative: no shell, an argv[0] allowlist, shell
metacharacters rejected, a hard timeout, and a capped output — safe to expose to
open-ended voice input.
"""

from __future__ import annotations

import datetime as _dt
import json as _json
import os
import shlex
import subprocess
import urllib.error
import urllib.parse

from config import CONFIG
from .registry import ToolSpec
from .web import _http_get


# --- current date / time ----------------------------------------------------

def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def get_current_datetime() -> dict:
    """Local wall-clock date and time (no args)."""
    now = _dt.datetime.now().astimezone()
    weekday = now.strftime("%A")
    month = now.strftime("%B")
    time_str = now.strftime("%-I:%M %p") if os.name != "nt" else now.strftime("%I:%M %p")
    tz = now.tzname() or ""
    spoken = f"{weekday}, {month} {_ordinal(now.day)}, {time_str}"
    return {
        "weekday": weekday,
        "date": now.strftime("%Y-%m-%d"),
        "time": time_str,
        "iso": now.isoformat(),
        "tz": tz,
        "spoken": spoken,
    }


# --- air quality (Open-Meteo, keyless) --------------------------------------

def _aqi_category(aqi: float | int | None) -> str:
    if aqi is None:
        return "unknown"
    aqi = float(aqi)
    if aqi <= 50:
        return "good"
    if aqi <= 100:
        return "moderate"
    if aqi <= 150:
        return "unhealthy for sensitive groups"
    if aqi <= 200:
        return "unhealthy"
    if aqi <= 300:
        return "very unhealthy"
    return "hazardous"


def _geocode(location: str) -> tuple[float, float, str]:
    loc = urllib.parse.quote(location)
    raw = _http_get(
        f"https://geocoding-api.open-meteo.com/v1/search?name={loc}&count=1&language=en&format=json",
        timeout=CONFIG.web.fetch_timeout,
    )
    data = _json.loads(raw)
    results = data.get("results") or []
    if not results:
        raise RuntimeError(f"Could not find a place named {location!r}")
    top = results[0]
    name = ", ".join(p for p in (top.get("name"), top.get("country_code")) if p)
    return float(top["latitude"]), float(top["longitude"]), name or location


def get_air_quality(location: str = "") -> dict:
    """Current air quality (US AQI, PM2.5/PM10) for a place, via Open-Meteo."""
    location = (location or "").strip() or os.environ.get("VA_DEFAULT_LOCATION", "").strip()
    if not location:
        raise ValueError("location is required (or set VA_DEFAULT_LOCATION)")
    lat, lon, name = _geocode(location)
    try:
        raw = _http_get(
            "https://air-quality-api.open-meteo.com/v1/air-quality"
            f"?latitude={lat}&longitude={lon}&current=us_aqi,pm2_5,pm10,ozone",
            timeout=CONFIG.web.fetch_timeout,
        )
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Air quality lookup failed: {exc}") from exc
    cur = (_json.loads(raw).get("current") or {})
    aqi = cur.get("us_aqi")
    category = _aqi_category(aqi)
    pm25 = cur.get("pm2_5")
    spoken = (
        f"Air quality in {name} is {category}"
        + (f", with a US AQI of {round(float(aqi))}" if aqi is not None else "")
        + (f" and PM2.5 at {pm25}" if pm25 is not None else "")
        + "."
    )
    return {
        "location": name,
        "us_aqi": aqi,
        "category": category,
        "pm2_5": pm25,
        "pm10": cur.get("pm10"),
        "ozone": cur.get("ozone"),
        "spoken": spoken,
    }


# --- guarded bash runner ----------------------------------------------------

_BASH_ALLOWLIST = frozenset({
    "date", "cal", "uptime", "uname", "df", "free", "whoami", "hostname",
})
_BASH_ALLOWED_ARGS = {
    "date": frozenset(),
    "cal": frozenset(),
    "uptime": frozenset(),
    "uname": frozenset({"-a", "--all", "-s", "--kernel-name", "-n", "--nodename",
                        "-r", "--kernel-release", "-v", "--kernel-version", "-m",
                        "--machine", "-p", "--processor", "-i", "--hardware-platform",
                        "-o", "--operating-system"}),
    "df": frozenset({"-h", "--human-readable", "-H", "--si", "-T", "--print-type",
                     "-i", "--inodes", "-P", "--portability"}),
    "free": frozenset({"-b", "--bytes", "-k", "--kibi", "-m", "--mebi", "-g",
                       "--gibi", "-h", "--human", "--si", "-t", "--total", "-w",
                       "--wide"}),
    "whoami": frozenset(),
    "hostname": frozenset({"-s", "--short", "-f", "--fqdn", "-d", "--domain",
                            "-i", "--ip-address", "-I", "--all-ip-addresses"}),
}
_BASH_FORBIDDEN = set(";|&$`><\n(){}*?!\\")
_BASH_MAX_OUTPUT = 2048


def run_bash(command: str) -> dict:
    """Run a whitelisted, argument-free-ish shell command with no shell interpolation."""
    command = (command or "").strip()
    if not command:
        return {"error": "command is required"}
    if any(ch in command for ch in _BASH_FORBIDDEN):
        return {"error": "command contains disallowed characters"}
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return {"error": f"could not parse command: {exc}"}
    if not argv:
        return {"error": "empty command"}
    if argv[0] not in _BASH_ALLOWLIST:
        return {"error": f"command {argv[0]!r} is not allowed",
                "allowed": sorted(_BASH_ALLOWLIST)}
    disallowed_args = [arg for arg in argv[1:] if arg not in _BASH_ALLOWED_ARGS[argv[0]]]
    if disallowed_args:
        return {
            "error": f"arguments are not allowed for command {argv[0]!r}: {disallowed_args!r}",
            "allowed_arguments": sorted(_BASH_ALLOWED_ARGS[argv[0]]),
        }
    try:
        proc = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return {"error": "command timed out"}
    except (OSError, ValueError) as exc:
        return {"error": f"execution failed: {exc}"}
    out = (proc.stdout or "").strip()
    if len(out) > _BASH_MAX_OUTPUT:
        out = out[:_BASH_MAX_OUTPUT] + "…"
    return {
        "command": " ".join(argv),
        "exit_code": proc.returncode,
        "output": out,
        "stderr": (proc.stderr or "").strip()[:512],
    }


# --- registration -----------------------------------------------------------

def build_system_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="get_current_datetime",
            description=(
                "Get the current local date and time. Use for any 'what day/date is it', "
                "'what time is it', 'what's today' question."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            handler=lambda a: get_current_datetime(),
            group="system",
        ),
        ToolSpec(
            name="get_air_quality",
            description=(
                "Get current air quality (US AQI, PM2.5) for a place. Use when asked about "
                "air quality, smog, pollution, or whether the air is safe."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City or place name. Optional if a default is set.",
                    },
                },
                "required": [],
            },
            handler=lambda a: get_air_quality(a.get("location", "")),
            group="system",
        ),
        ToolSpec(
            name="run_bash",
            description=(
                "Run a safe, read-only shell command from a fixed allowlist "
                "(date, cal, uptime, uname, df, free, whoami, hostname) and return its output."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "A single allowlisted command, e.g. 'date' or 'uptime'.",
                    },
                },
                "required": ["command"],
            },
            handler=lambda a: run_bash(a.get("command", "")),
            group="system",
            execution_timeout=8.0,
        ),
    ]
