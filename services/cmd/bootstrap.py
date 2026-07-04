"""Explicit cmd registration — manually maintained $PATH."""

from __future__ import annotations

from services.cmd.executors.builtin import exec_help, exec_status
from services.cmd.executors.blender import exec_blend
from services.cmd.executors.imagine import exec_imagine
from services.cmd.models import CmdDefinition, CmdParameter, CmdSurface
from services.cmd.registry import registry

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
                ),
                CmdParameter(
                    name="model",
                    type="string",
                    description="Optional model/provider choice",
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
                "/imagine castle sunset",
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
