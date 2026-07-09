"""Gateway lifespan — load voice agent, seed personality, apply discord env."""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from services.paths import DATA_DIR
from services.discord.unified_bot import apply_discord_env, start_discord_extensions
from services.settings.store import apply_to_config, seed_env_defaults
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
    if os.getenv("MAYA_E2E_FIXTURES"):
        from services.music.e2e_fixtures import seed_andrea_fetch_cache

        seed_andrea_fetch_cache()
    migrate_qwen3_data_to_unified()
    os.environ.setdefault("VA_DATA_DIR", str(DATA_DIR))
    seed_examples_if_needed()
    await _seed_operator_account()
    settings = seed_env_defaults()
    platform = settings.get("platform", {}) or {}
    otel_on = platform.get("otel_enabled") or os.getenv("VA_OTEL_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if otel_on:
        os.environ["VA_OTEL_ENABLED"] = "1"
        try:
            from observability import setup_observability

            setup_observability()
        except ImportError:
            log.debug("otel setup skipped (observability module unavailable)")
    apply_discord_env(settings)
    apply_to_config(settings)

    # All-in-one: bring up Qwen3-ASR beside the gateway when dictation asks for it.
    try:
        from services.voice.asr_sidecar import (
            ensure_asr_sidecar,
            stop_asr_sidecar,
            wait_for_asr_ready,
        )

        asr_info = ensure_asr_sidecar(settings)
        if asr_info.get("started") or asr_info.get("reason") == "already_running":
            # Align settings CONFIG URL after sidecar may rewrite 8001 → 8091.
            apply_to_config(settings)
            ready = await asyncio.to_thread(wait_for_asr_ready, settings)
            if not ready:
                log.warning("ASR sidecar warming slowly — voice agent may use Whisper until ready")
        elif asr_info.get("reason") not in {"autostart_disabled"}:
            log.warning("ASR sidecar not started: %s", asr_info)
    except Exception as exc:  # noqa: BLE001
        log.warning("ASR sidecar startup skipped: %s", exc)

    from services.discovery.registry import probe_all

    probe_all(settings=settings)

    try:
        from services.integrations.google.config import (  # noqa: PLC0415
            GOOGLE_CLIENT_ID,
            GOOGLE_CONNECT_REDIRECT_URI,
            GOOGLE_LOGIN_REDIRECT_URI,
            dynamic_redirect_enabled,
            google_oauth_configured,
        )

        if google_oauth_configured():
            log.info(
                "Google OAuth configured client_id=...%s login_redirect=%s connect_redirect=%s dynamic=%s",
                GOOGLE_CLIENT_ID[-12:] if len(GOOGLE_CLIENT_ID) > 12 else GOOGLE_CLIENT_ID,
                GOOGLE_LOGIN_REDIRECT_URI,
                GOOGLE_CONNECT_REDIRECT_URI,
                dynamic_redirect_enabled(),
            )
    except Exception as exc:  # noqa: BLE001
        log.debug("Google OAuth startup log skipped: %s", exc)

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
    try:
        from services.voice.asr_sidecar import stop_asr_sidecar

        stop_asr_sidecar()
    except Exception as exc:  # noqa: BLE001
        log.debug("ASR sidecar shutdown skipped: %s", exc)
    hub.prepare_shutdown()
