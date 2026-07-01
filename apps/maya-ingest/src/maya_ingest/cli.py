"""Maya ingest entrypoints."""

from __future__ import annotations

import asyncio
import sys

from maya_ingest.flows import (
    analyze_release,
    backfill_catalogue,
    embed_pending,
    enrich_video,
    parse_video_intel,
    poll_music_sources,
    poll_subscriptions,
    research_flow,
    resolve_person_for_channel,
    video_comment_lifecycle,
)

_FLOWS = {
    "poll": poll_subscriptions,
    "poll-music": poll_music_sources,
    "embed": embed_pending,
    "enrich": enrich_video,
    "lifecycle": video_comment_lifecycle,
    "resolve": resolve_person_for_channel,
    "backfill": backfill_catalogue,
    "analyze-release": analyze_release,
    "parse-intel": parse_video_intel,
    "research": research_flow,
}


def run() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in _FLOWS:
        print(f"usage: maya-ingest <{'|'.join(_FLOWS)}> [args...]", file=sys.stderr)
        sys.exit(2)
    flow = _FLOWS[sys.argv[1]]
    args = sys.argv[2:]
    asyncio.run(flow(*args))
