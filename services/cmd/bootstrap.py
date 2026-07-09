"""Explicit cmd registration — manually maintained $PATH."""

from __future__ import annotations

from services.cmd.executors.builtin import exec_help, exec_status
from services.cmd.executors.blender import exec_blend
from services.cmd.executors.imagine import exec_imagine
from services.cmd.executors.play import exec_play
from services.cmd.executors.queue import exec_queue
from services.cmd.models import CmdDefinition, CmdParameter, CmdSurface
from services.cmd.registry import registry
from services.game.enabled import GAME_MODE_ENABLED

_bootstrapped = False


def ensure_cmds_registered() -> None:
    global _bootstrapped
    if _bootstrapped:
        return
    _bootstrapped = True
    if registry.get("help") is not None:
        # Registry already populated — e.g. a test fixture reset the flag
        # without clearing the registry. Re-registering would raise.
        return

    registry.register(
        CmdDefinition(
            id="help",
            name="help",
            description="List available cmds for this surface",
            category="Utilities",
            aliases=["cmds", "commands"],
            icon="question",
            tags=["help", "discovery"],
            surfaces=[CmdSurface.CHAT, CmdSurface.DASHBOARD, CmdSurface.DISCORD],
            examples=["/help"],
            executor=exec_help,
        )
    )

    registry.register(
        CmdDefinition(
            id="status",
            name="status",
            description="Show agent and LLM readiness",
            category="System",
            icon="activity",
            tags=["health", "readiness", "system"],
            surfaces=[CmdSurface.CHAT, CmdSurface.DASHBOARD, CmdSurface.DISCORD],
            examples=["/status"],
            executor=exec_status,
        )
    )

    registry.register(
        CmdDefinition(
            id="imagine",
            name="imagine",
            description="Generate an image from a prompt",
            category="Media",
            aliases=["img"],
            icon="image",
            tags=["image", "stable diffusion", "flux", "photo"],
            surfaces=[CmdSurface.CHAT, CmdSurface.DASHBOARD, CmdSurface.DISCORD],
            parameters=[
                CmdParameter(
                    name="prompt",
                    type="string",
                    required=True,
                    description="Prompt for the image workflow",
                ),
                CmdParameter(
                    name="mode",
                    type="string",
                    default="generate",
                    choices=["generate"],
                    hidden_choices=["arena"],
                ),
                CmdParameter(
                    name="model",
                    type="string",
                    description="Optional model/provider choice (zit, krea2, ideogram-local)",
                ),
                CmdParameter(
                    name="size",
                    type="string",
                    default="1024x1024",
                ),
                CmdParameter(
                    name="quality",
                    type="string",
                    default="high",
                ),
            ],
            examples=[
                "/imagine cyberpunk city",
                "/imagine castle sunset model=krea2",
                "/img cat sitting on a windowsill",
            ],
            executor=exec_imagine,
        )
    )

    registry.register(
        CmdDefinition(
            id="blend",
            name="blend",
            description="Control Blender via MCP (summary, screenshot, render, inspect, code)",
            category="Creative",
            icon="box",
            tags=["blender", "3d", "mcp", "render"],
            surfaces=[CmdSurface.CHAT, CmdSurface.DASHBOARD, CmdSurface.DISCORD],
            parameters=[
                CmdParameter(
                    name="action",
                    type="string",
                    default="summary",
                    choices=["summary", "inspect", "screenshot", "render", "code"],
                    description="Blender action to run",
                ),
                CmdParameter(
                    name="file",
                    type="string",
                    description="Path to a .blend file (inspect / CLI code)",
                ),
                CmdParameter(
                    name="code",
                    type="string",
                    description="Python code for the code action",
                ),
            ],
            examples=[
                "/blend",
                "/blend screenshot",
                "/blend render",
                "/blend inspect /path/to/scene.blend",
                "/blend code import bpy; result = [o.name for o in bpy.data.objects]",
            ],
            executor=exec_blend,
        )
    )

    registry.register(
        CmdDefinition(
            id="play",
            name="play",
            description="Queue music into Discord voice (URL, Bandcamp album, or search)",
            category="Media",
            aliases=["p"],
            icon="music",
            tags=["music", "audio", "discord", "bandcamp", "youtube", "queue"],
            surfaces=[CmdSurface.CHAT, CmdSurface.DASHBOARD, CmdSurface.DISCORD],
            parameters=[
                CmdParameter(
                    name="query",
                    type="string",
                    # Optional so a bare /play (resume) passes validate_args; the
                    # executor re-derives the full query from ctx.raw_text.
                    required=False,
                    description="URL, Bandcamp album link, or search text (empty resumes playback)",
                ),
            ],
            examples=[
                "/play https://00000ooooo.bandcamp.com/album/--5",
                "/play daft punk one more time",
                "/play",
            ],
            executor=exec_play,
        )
    )

    registry.register(
        CmdDefinition(
            id="queue",
            name="queue",
            description="Add music to the dashboard player queue without stopping playback",
            category="Media",
            icon="music",
            tags=["music", "audio", "dashboard", "queue"],
            surfaces=[CmdSurface.CHAT, CmdSurface.DASHBOARD],
            parameters=[
                CmdParameter(
                    name="query",
                    type="string",
                    required=True,
                    description="URL or search text to append to the queue",
                ),
            ],
            examples=[
                "/queue gangnam style",
                "/queue hyuna bubble pop",
            ],
            executor=exec_queue,
        )
    )

    if GAME_MODE_ENABLED:
        from services.cmd.executors.game import exec_game

        registry.register(
            CmdDefinition(
                id="game",
                name="game",
                description=(
                    "Play a video game on the emulator autonomously until a goal is reached "
                    "(Pokemon/mGBA). Maya narrates each step and keeps playing on her own."
                ),
                category="Games",
                aliases=["gamegoal", "playgame"],
                icon="gamepad",
                tags=["pokemon", "emulator", "mgba", "game", "autonomous"],
                surfaces=[CmdSurface.CHAT, CmdSurface.DASHBOARD],
                parameters=[
                    CmdParameter(
                        name="goal",
                        type="string",
                        required=True,
                        description="Clear win condition visible on screen",
                    ),
                    CmdParameter(
                        name="profile_id",
                        type="string",
                        default="pokemon_gba",
                        description="Game profile id (default pokemon_gba)",
                    ),
                ],
                examples=[
                    "/game get through Professor Oak intro",
                    "/game reach the end of the game",
                    "/game choose starter Pokemon",
                ],
                executor=exec_game,
            )
        )
