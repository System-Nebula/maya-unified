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
from services.voice.hub import hub
from services.voice.personality_seed import seed_personality_if_needed

log = logging.getLogger("maya-unified.gateway")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import os

    install_loop_handler()
    os.makedirs(DATA_DIR, exist_ok=True)
    migrate_qwen3_data_to_unified()
    os.environ.setdefault("VA_DATA_DIR", str(DATA_DIR))
    seed_personality_if_needed()
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
