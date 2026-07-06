"""Tests for Maya-unified memory rebind, migration, and edit APIs."""

from __future__ import annotations

import gc
import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
VOICE_RUNTIME = ROOT / "packages" / "voice-runtime"
if str(VOICE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(VOICE_RUNTIME))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import CONFIG  # noqa: E402
from memory.manager import MemoryManager  # noqa: E402
from memory.skills import SkillStore  # noqa: E402


def _load_memory_migration():
    path = ROOT / "services" / "operator_voice" / "memory_migration.py"
    spec = importlib.util.spec_from_file_location("memory_migration", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_memory_manager_rebind_switches_data_dir():
    with tempfile.TemporaryDirectory() as tmp:
        dir_a = os.path.join(tmp, "operator-a")
        dir_b = os.path.join(tmp, "operator-b")
        os.makedirs(os.path.join(dir_a, "memory"), exist_ok=True)
        os.makedirs(os.path.join(dir_b, "memory"), exist_ok=True)
        (Path(dir_a) / "memory" / "MEMORY.md").write_text("Fact A§", encoding="utf-8")
        (Path(dir_b) / "memory" / "MEMORY.md").write_text("Fact B§", encoding="utf-8")

        CONFIG.memory.data_dir = dir_a
        CONFIG.memory.cognitive_enabled = False
        mgr = MemoryManager(llm=MagicMock(), emit=None)
        try:
            assert "Fact A" in str(mgr.curated.snapshot()["memory"])
            mgr.rebind(dir_b)
            assert mgr._bound_data_dir == os.path.abspath(dir_b)
            assert "Fact B" in str(mgr.curated.snapshot()["memory"])
            assert "Fact A" not in str(mgr.curated.snapshot()["memory"])
        finally:
            del mgr
            gc.collect()


def test_copy_global_memory_to_operator_idempotent():
    mig = _load_memory_migration()
    with tempfile.TemporaryDirectory() as tmp:
        global_root = Path(tmp) / "data"
        global_mem = global_root / "memory"
        global_mem.mkdir(parents=True)
        (global_mem / "MEMORY.md").write_text("Global fact§", encoding="utf-8")
        (global_root / "skills").mkdir()
        (global_root / "skills" / "demo.md").write_text("# Demo\n\nSteps", encoding="utf-8")

        op_id = "test-operator-1"
        op_dir = global_root / "operators" / op_id
        op_dir.mkdir(parents=True)
        (op_dir / "memory").mkdir()
        (op_dir / "memory" / "MEMORY.md").write_text("", encoding="utf-8")

        original_data_dir = mig.DATA_DIR
        try:
            mig.DATA_DIR = global_root
            assert mig.copy_global_memory_to_operator(op_id) is True
            assert (op_dir / "memory" / "MEMORY.md").read_text(encoding="utf-8") == "Global fact§"
            assert (op_dir / "skills" / "demo.md").is_file()
            assert (op_dir / ".imported-from-global").is_file()
            assert mig.copy_global_memory_to_operator(op_id) is False
        finally:
            mig.DATA_DIR = original_data_dir


def test_skill_store_delete():
    with tempfile.TemporaryDirectory() as tmp:
        store = SkillStore(tmp)
        store.write("hello-world", "# Hello\n\nDo the thing.")
        path = Path(tmp) / "skills" / "hello-world.md"
        assert path.is_file()
        res = store.delete("hello-world")
        assert res["success"] is True
        assert not path.is_file()


def test_hub_chat_text_schedules_review():
    hub_src = (ROOT / "services" / "voice" / "hub.py").read_text(encoding="utf-8")
    assert "self.agent.memory.log_turn(text, reply)" in hub_src
    assert "self.agent.memory.schedule_review(text, reply)" in hub_src


def test_memory_routes_expose_edit_endpoints():
    routes_src = (ROOT / "apps" / "gateway" / "voice_routes.py").read_text(encoding="utf-8")
    assert "/memory-cognitive-edit" in routes_src
    assert "/memory-skill-edit" in routes_src
    assert "/memory-cognitive" in routes_src


def test_agent_exposes_rebind_and_cognitive_edit():
    agent_src = (ROOT / "packages" / "voice-runtime" / "agent.py").read_text(encoding="utf-8")
    assert "def rebind_memory" in agent_src
    assert "def edit_cognitive_memory" in agent_src
    assert "def edit_skill" in agent_src


def test_cognitive_update_reembeds():
    with tempfile.TemporaryDirectory() as tmp:
        from memory.cognitive import CognitiveMemory

        cog = CognitiveMemory(tmp, embed_model="BAAI/bge-small-en-v1.5", emit=None)
        cog._embed = lambda _text: [1.0, 0.0, 0.0]  # type: ignore[method-assign]
        try:
            stored = cog.store("Original fact", importance=0.5)
            assert stored.get("success") is True
            mid = cog.list_entries(limit=1, offset=0)["entries"][0]["id"]
            updated = cog.update(mid, content="Updated fact", importance=0.8)
            assert updated.get("success") is True
            row = cog.list_entries(limit=1, offset=0)["entries"][0]
            assert row["content"] == "Updated fact"
            assert row["importance"] == 0.8
        finally:
            conn = getattr(cog._local, "conn", None)
            if conn is not None:
                conn.close()
                cog._local.conn = None
            del cog
            gc.collect()
