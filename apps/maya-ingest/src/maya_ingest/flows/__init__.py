"""Prefect flows."""

from maya_ingest.flows.analyze_release import analyze_release
from maya_ingest.flows.atom_poll import poll_subscriptions
from maya_ingest.flows.backfill_catalogue import backfill_catalogue
from maya_ingest.flows.comment_lifecycle import video_comment_lifecycle
from maya_ingest.flows.embed_batch import embed_pending
from maya_ingest.flows.enrich_video import enrich_video
from maya_ingest.flows.parse_video_intel import parse_video_intel
from maya_ingest.flows.poll_music_sources import poll_music_sources
from maya_ingest.flows.research_flow import research_flow
from maya_ingest.flows.resolve_person import resolve_person_for_channel

__all__ = [
    "analyze_release",
    "backfill_catalogue",
    "embed_pending",
    "enrich_video",
    "parse_video_intel",
    "poll_music_sources",
    "poll_subscriptions",
    "resolve_person_for_channel",
    "research_flow",
    "video_comment_lifecycle",
]
