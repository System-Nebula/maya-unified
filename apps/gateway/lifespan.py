"""Gateway lifespan — load voice agent, seed personality, apply discord env."""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from services.paths import DATA_DIR
from services.discord.unified_bot import apply_discord_env, start_discord_extensions
from services.settings.store import load_settings, apply_to_config
from apps.gateway.asyncio_compat import install_loop_handler
from services.voice.data_migration import migrate_qwen3_data_to_unified
from services.voice.example_seed import seed_examples_if_needed
from services.voice.hub import hub
from services.auth.seed import seed_default_operator_if_needed
from services.auth.operator_store import get_db_session

log = logging.getLogger("maya-unified.gateway")


async def _seed_operator_account() -> None:
    try:
        async for session in get_db_session():
            await seed_default_operator_if_needed(session)
            from services.operator_voice.context import import_legacy_global_to_admin

            await import_legacy_global_to_admin(session)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("operator seed skipped: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    import os

    from services.async_bridge import set_main_loop

    set_main_loop(asyncio.get_running_loop())
    install_loop_handler()
    os.makedirs(DATA_DIR, exist_ok=True)
    migrate_qwen3_data_to_unified()
    os.environ.setdefault("VA_DATA_DIR", str(DATA_DIR))
    seed_examples_if_needed()
    await _seed_operator_account()
    settings = load_settings()
    apply_discord_env(settings)
    apply_to_config(settings)
    threading.Thread(target=hub.load_agent, daemon=True, name="voice-agent-load").start()

    def _after_ready():
        import time

        for _ in range(120):
            if hub.ready:
                start_discord_extensions(hub)
                return
            time.sleep(0.5)

    threading.Thread(target=_after_ready, daemon=True).start()
    yield
