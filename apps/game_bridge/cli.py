"""CLI for Maya game bridge."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from apps.game_bridge.runner import GameBridgeRunner  # noqa: E402
from services.game.profiles import load_profile  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Maya game bridge — Neuro client for emulators")
    parser.add_argument("command", choices=["run"], nargs="?", default="run")
    parser.add_argument("--profile", default="pokemon_gba", help="Game profile id")
    parser.add_argument("--gateway", default="http://127.0.0.1:8090", help="Maya gateway URL")
    parser.add_argument("--token", default="", help="maya_op_session cookie value")
    parser.add_argument("--ws", default="", help="WebSocket URL override")
    parser.add_argument("--capture", default="", help="Capture backend override")
    parser.add_argument("--max-turns", type=int, default=0, help="Stop after N turns (0=unlimited)")
    parser.add_argument(
        "--goal",
        default="",
        help="Autonomous goal — Maya plays and narrates until reached on screen",
    )
    parser.add_argument(
        "--autonomous",
        action="store_true",
        help="Play autonomously (picks goal from API if --goal omitted)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.token:
        print("Error: --token required (copy maya_op_session cookie from browser)", file=sys.stderr)
        return 1

    profile = load_profile(args.profile)
    runner = GameBridgeRunner(
        profile=profile,
        gateway=args.gateway,
        token=args.token,
        ws_url=args.ws or None,
        capture_mode=args.capture or None,
    )
    max_turns = args.max_turns if args.max_turns > 0 else None
    if args.goal or args.autonomous:
        max_turns = None  # autonomous runs until goal
    try:
        runner.run(
            max_turns=max_turns,
            goal=args.goal,
            autonomous=args.autonomous or bool(args.goal),
        )
    except KeyboardInterrupt:
        runner.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
