"""Entrypoint for the Qwen3 streaming voice agent.

Modes:
    --mode typed   Type text, hear the voice reply. No mic needed.
    --mode ptt     Push-to-talk: press Enter, speak for --seconds, get a reply.
    --mode vad     Hands-free: VAD detects your turn; barge-in cuts off the AI.

Run:
    python app.py --mode typed
    python app.py --mode ptt --seconds 5
    python app.py --mode vad
    python app.py --list-speakers      # CustomVoice mode speaker IDs
"""

from __future__ import annotations

import argparse
import sys

# Make console output robust to characters the Windows code page can't encode
# (e.g. emoji), so a stray character never crashes a turn.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from observability import setup_observability

setup_observability()


def main() -> None:
    parser = argparse.ArgumentParser(description="Qwen3-TTS streaming voice agent")
    parser.add_argument("--mode", choices=["typed", "ptt", "vad"], default="typed")
    parser.add_argument("--seconds", type=float, default=5.0, help="push-to-talk record length")
    parser.add_argument(
        "--list-speakers",
        action="store_true",
        help="Load the configured TTS model and print available CustomVoice speaker IDs, then exit.",
    )
    args = parser.parse_args()

    if args.list_speakers:
        from tts import Qwen3TTS

        voice = Qwen3TTS()
        speakers = voice.list_speakers()
        if speakers:
            print("Available speakers:")
            for s in speakers:
                print(f"  {s}")
        else:
            print("No speakers reported (custom mode requires a CustomVoice model).")
        return

    from agent import VoiceAgent

    agent = VoiceAgent(mode=args.mode, ptt_seconds=args.seconds)
    agent.run()


if __name__ == "__main__":
    main()
