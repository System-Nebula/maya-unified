"""DB-001: Alembic has a single merge head."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def _script() -> ScriptDirectory:
    root = Path(__file__).resolve().parents[1] / "packages" / "maya-db"
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    return ScriptDirectory.from_config(cfg)


def test_alembic_has_exactly_one_head() -> None:
    heads = _script().get_heads()
    assert len(heads) == 1, f"expected one alembic head, got {heads}"
    assert heads[0] == "20260712_merge_msg_ids_browser_capture"


def test_merge_revision_parents_are_former_heads() -> None:
    script = _script()
    rev = script.get_revision("20260712_merge_msg_ids_browser_capture")
    assert rev is not None
    parents = set(rev.down_revision if isinstance(rev.down_revision, tuple) else (rev.down_revision,))
    assert parents == {"20260703_msg_ids", "20260708_browser_capture"}
