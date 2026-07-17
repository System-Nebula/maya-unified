"""TEST-002: security regression suite gate + canonical cross-operator SSE checks."""

from __future__ import annotations

import ast

import pytest

from services.voice.audience import Audience
from services.voice.hub import VoiceHub
from tests.security.suite_manifest import REQUIRED_SECURITY_MODULES, SUITE_ROOT, required_paths


def _drain(queue) -> list[dict]:
    events: list[dict] = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


@pytest.mark.security
def test_required_security_modules_present() -> None:
    missing = [
        f"{name}:{rel}"
        for name, rel in REQUIRED_SECURITY_MODULES
        if not (SUITE_ROOT / rel).is_file()
    ]
    assert not missing, f"TEST-002 missing modules: {missing}"


@pytest.mark.security
def test_required_modules_define_tests() -> None:
    empty: list[str] = []
    for name, rel in REQUIRED_SECURITY_MODULES:
        tree = ast.parse((SUITE_ROOT / rel).read_text(encoding="utf-8"))
        tests = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        ]
        if not tests:
            empty.append(f"{name}:{rel}")
    assert not empty, f"TEST-002 modules with no tests: {empty}"


@pytest.mark.security
def test_suite_path_list_is_nonempty_and_unique() -> None:
    paths = required_paths()
    assert len(paths) >= 10
    assert len(paths) == len(set(paths))


@pytest.mark.security
def test_cross_operator_sse_isolation() -> None:
    """Canonical suite check: operator A events never reach operator B."""
    hub = VoiceHub()
    op_a = hub.subscribe(operator_id="op-a")
    op_b = hub.subscribe(operator_id="op-b")
    _drain(op_a)
    _drain(op_b)

    hub.broadcast({"type": "ai", "text": "private-a"}, operator_id="op-a")
    hub.broadcast(
        {
            "type": "status",
            "value": "thinking",
            "audience": Audience.operator("op-a").to_dict(),
        }
    )

    a_types = [e.get("type") for e in _drain(op_a)]
    assert "ai" in a_types
    assert "status" in a_types
    assert not _drain(op_b)


@pytest.mark.security
def test_room_guest_cannot_see_operator_private_events() -> None:
    hub = VoiceHub()
    op = hub.subscribe(operator_id="op-a")
    guest = hub.subscribe(room_id="room-x")
    _drain(op)
    _drain(guest)

    hub.broadcast({"type": "user", "text": "secret"}, operator_id="op-a")
    hub.broadcast(
        {
            "type": "audio",
            "data": "pcm",
            "audience": Audience.operator("op-a").to_dict(),
        }
    )

    assert _drain(op)
    assert not _drain(guest)
