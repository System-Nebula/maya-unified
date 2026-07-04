---
title: Glossary
tags: [reference, glossary]
aliases: [Reference/Glossary, Glossary]
---

# Glossary

Terms used across Maya Unified documentation, dashboard UI, and codebase. Cross-links point to deeper guides.

## A

**Agent (VoiceAgent)**  
The voice-runtime orchestrator in `packages/voice-runtime/agent.py` that connects STT, LLM tool loop, TTS, and playback. Wrapped by [[Services/Voice Hub]] for operator scoping.

**Arena**  
Blind A/B image comparison mode where voters pick between two ComfyUI workflow outputs. ELO ratings stored in Postgres. Entry: Discord `/imagine mode:Arena` ([[Platform/Maya Bot]]) or `/api/arena/*` APIs.

## B

**Barge-in**  
User speech interrupting active TTS playback. Modes: `smart`, `instant`, `off` — configured under settings `detection.barge_mode`. See [[Voice Runtime/VAD and Barge-in]].

**Bundled examples**  
Shipped assets in `examples/` copied to runtime on first start — voices, personalities, skills. See [[Getting Started/Bundled Examples]].

## C

**Character card / Personality**  
JSON or PNG profile defining system prompt, voice reference, and metadata. Stored per-operator under `data/operators/{id}/`. See [[Configuration/Personalities]].

**ComfyUI**  
Node-based image generation engine; Maya accesses it via comfyui-api on port 3000. See [[Operations/ComfyUI]].

**Contracts (maya-contracts)**  
Pydantic schemas for public APIs. See [[Packages/Maya Contracts]].

## D

**Degraded mode**  
Gateway running without TTS (or partial subsystems) when model load fails. Text chat and Discord may still work. Set `VA_TTS_ENABLED=0` to skip TTS intentionally.

**Delivery cue (`VOICE:`)**  
Optional LLM prefix stripped before display/TTS; emitted as separate SSE `delivery` event when style cues enabled.

**Discover**  
Platform feed ranking and inbox APIs under `/api/discover/*`. Powered by [[Packages/Maya Feeds]] and [[Packages/Maya Graph]].

## E

**Effective settings**  
Merged view of global `data/settings.json` plus operator overlay — what the dashboard displays. See [[Services/Settings Store]].

## G

**Guest room**  
Multi-user voice session at `/room/{slug}` with queue-based mic sharing. APIs under `/api/rooms/{slug}/*` with guest tokens.

## H

**Hub (VoiceHub)**  
Unified singleton in `services/voice/hub.py` bridging FastAPI to voice-runtime. See [[Services/Voice Hub]].

## I

**Ingest**  
Prefect flows in [[Platform/Maya Ingest]] polling external feeds into Postgres.

## L

**Lease (voice lease)**  
Exclusive lock granting one operator or room access to the mic/TTS pipeline at a time. Exposed in `/api/voice/agent/status`.

**LiteLLM**  
Optional reasoning provider routing multiple LLM backends. Settings: `reasoning.provider = litellm`.

## M

**MCP (Model Context Protocol)**  
Optional tool transport when `tools.mcp_enabled` true. Install `pip install -e ".[mcp]"`.

## O

**Operator**  
Dashboard user with local account in `operator_users` table — not the same as "platform user" in legacy maya-public invite flows. See [[Operations/Operator Auth]].

**Operator overlay**  
Per-operator settings JSON overriding global defaults.

## P

**Persona**  
High-level reasoning style preset in settings (`reasoning.persona`): maya, operator, assistant, etc.

**PKCE**  
Proof Key for Code Exchange — OAuth extension used for Google login and connect flows. See [[Operations/Google OAuth]].

**Platform**  
Optional feature tier: arena, discover, research, registry, music — requires Postgres and `uv sync --all-packages`. See [[Platform/Maya Gateway]].

**Prefect**  
Workflow orchestrator used by maya-ingest for scheduled feed polling.

## R

**Reasoning LLM**  
The chat model driving agent responses (distinct from optional `reasoning_model` for tool planning). Configured in Settings → Reasoning.

## S

**SSE (Server-Sent Events)**  
One-way event stream at `GET /api/voice/agent/events` for chat tokens, audio, settings updates.

**Skill**  
Markdown instruction file in `data/skills/` extending agent behavior. See [[Configuration/Skills]].

**STT / TTS**  
Speech-to-text (Whisper / Wispr) and text-to-speech (Qwen TTS). See [[Voice Runtime/STT]] and [[Voice Runtime/TTS]].

## U

**Unified gateway**  
Single FastAPI app at `apps/gateway/main.py` serving dashboard, voice agent APIs, and optional platform routes. See [[Apps/Unified Gateway]].

## V

**Voice-runtime**  
Package at `packages/voice-runtime/` containing the qwen3 voice engine. See [[Voice Runtime]].

**VRM**  
3D avatar model format rendered in dashboard viewer; lip sync from TTS spectrum.

**VTube Studio (VTS)**  
External app receiving expression hotkeys from agent via settings `vts.*`.

**WebLLM**  
Browser-side LLM inference; gateway brokers tokens via `/api/voice/agent/webllm/*` endpoints.

## W

**Wiki link**  
Documentation cross-reference syntax: `[[Services/Voice Hub]]` in Quartz docs.

## Related documentation

- [[Architecture/Overview]] — system map
- [[Reference/API]] — HTTP terminology in routes
- [[Reference/Environment Index]] — configuration variables
