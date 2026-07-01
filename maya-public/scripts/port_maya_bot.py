#!/usr/bin/env python3
"""Port Discord bot (imagine cog only) into apps/maya-bot."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

PRIVATE = Path.home() / "Workspace"
PUBLIC = Path(__file__).resolve().parents[1]
DEST = PUBLIC / "apps" / "maya-bot" / "src" / "maya_bot"

REWRITES = [
    (r"\bfrom lib\.image\.", "from maya_image."),
    (r"\bfrom lib\.arena\.", "from maya_image.arena."),
    (r"\bfrom lib\.auth\.identity import", "from maya_image.auth.identity import"),
    (r"\bfrom lib\.portal\.activity import", "from maya_image.portal.activity import"),
    (r"\bfrom lib\.types\.image_job import", "from maya_image.types.image_job import"),
    (r"\bfrom bot\.main import", "from maya_bot.main import"),
]


def rewrite(content: str) -> str:
    for pattern, repl in REWRITES:
        content = re.sub(pattern, repl, content)
    return content


def main() -> None:
    if DEST.exists():
        shutil.rmtree(DEST.parent)
    (DEST / "cogs").mkdir(parents=True)

    imagine = rewrite((PRIVATE / "src/maya/bot/cogs/imagine.py").read_text())
    imagine = imagine.replace(
        '''    def _portal_link_bypass_active(self, interaction: discord.Interaction) -> bool:
        flag = os.getenv("IMAGINE_SKIP_PORTAL_LINK", "").strip().lower()
        if flag not in ("1", "true", "yes"):
            return False
        test_guild = os.getenv("TEST_GUILD_ID", "").strip()
        if not test_guild or interaction.guild_id is None:
            return False
        return str(interaction.guild_id) == test_guild
''',
        '''    def _portal_link_bypass_active(self, interaction: discord.Interaction) -> bool:
        flag = os.getenv("IMAGINE_SKIP_PORTAL_LINK", "1").strip().lower()
        if flag not in ("1", "true", "yes"):
            return False
        test_guild = os.getenv("TEST_GUILD_ID", "").strip()
        if test_guild and interaction.guild_id is not None:
            return str(interaction.guild_id) == test_guild
        return True
''',
    )
    (DEST / "cogs" / "imagine.py").write_text(imagine)
    (DEST / "cogs" / "__init__.py").write_text("")

    main_src = (PRIVATE / "src/maya/bot/main.py").read_text()
    main_src = rewrite(main_src)
    main_src = main_src.replace(
        '''    root = Path(__file__).resolve().parents[3]
    load_dotenv(root / ".env")
    load_dotenv(root / "src" / "maya" / ".env", override=True)''',
        '''    root = Path(__file__).resolve().parents[3]
    load_dotenv(root / ".env")
    load_dotenv(root / "apps" / "maya-bot" / ".env", override=True)''',
    )
    main_src = main_src.replace(
        '''        for extension in (
            "bot.cogs.follow",
            "bot.cogs.ask",
            "bot.cogs.tts",
            "bot.cogs.arena",
            "bot.cogs.imagine",
            "bot.cogs.music",
            "bot.cogs.voice_transcription",
        ):''',
        '''        for extension in ("maya_bot.cogs.imagine",):''',
    )
    main_src = main_src.replace("class MayaBot", "class MayaBot")
    main_src = main_src.replace("from bot.main import", "from maya_bot.main import")
    main_src = main_src.replace(
        '''@dataclass(slots=True)
class MayaSettings:
    crawler_url: str = os.getenv("CRAWLER_URL", "http://localhost:8001")
    feed_url: str = os.getenv("FEED_URL", "http://localhost:8002")
    allowed_user_ids: set[int] | None = None
    cloud_transcription_enabled: bool = os.getenv("CLOUD_TRANSCRIPTION_ENABLED", "").lower() in ("1", "true", "yes")
    transcription_gateway_url: str = os.getenv("TRANSCRIPTION_GATEWAY_URL", "ws://localhost:8765")

    @classmethod
    def from_env(cls) -> "MayaSettings":
        raw_allowed = (os.getenv("ALLOWED_USER_IDS") or "").strip()
        allowed = {
            int(value.strip())
            for value in raw_allowed.split(",")
            if value.strip().isdigit()
        }
        return cls(
            crawler_url=os.getenv("CRAWLER_URL", "http://localhost:8001"),
            feed_url=os.getenv("FEED_URL", "http://localhost:8002"),
            allowed_user_ids=allowed or None,
            cloud_transcription_enabled=os.getenv("CLOUD_TRANSCRIPTION_ENABLED", "").lower() in ("1", "true", "yes"),
            transcription_gateway_url=os.getenv("TRANSCRIPTION_GATEWAY_URL", "ws://localhost:8765"),
        )
''',
        '''@dataclass(slots=True)
class MayaSettings:
    allowed_user_ids: set[int] | None = None

    @classmethod
    def from_env(cls) -> "MayaSettings":
        raw_allowed = (os.getenv("ALLOWED_USER_IDS") or "").strip()
        allowed = {
            int(value.strip())
            for value in raw_allowed.split(",")
            if value.strip().isdigit()
        }
        return cls(allowed_user_ids=allowed or None)
''',
    )
    (DEST / "main.py").write_text(main_src)
    (DEST / "__init__.py").write_text('"""Maya Discord bot — ComfyUI /imagine arena harness."""\n')
    (DEST / "launcher.py").write_text(
        '''"""Console entrypoint for maya-bot."""

from maya_bot.main import main

if __name__ == "__main__":
    main()
'''
    )
    print(f"Ported maya-bot to {DEST}")


if __name__ == "__main__":
    main()
