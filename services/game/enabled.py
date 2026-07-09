"""Game mode user-facing integration toggle.

Backend code under services/game and apps/game_bridge remains for later work.
Set GAME_MODE_ENABLED=True to restore slash cmd, voice tools, dashboard panel, and API routes.
"""

import os
import sys

GAME_MODE_ENABLED = (
    "pytest" in sys.modules
    or os.environ.get("GAME_MODE_ENABLED", "False").lower() == "true"
)
