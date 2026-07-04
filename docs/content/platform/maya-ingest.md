---
title: Maya Ingest
tags: [platform, ingest, prefect]
aliases: [Platform/Maya Ingest]
---

# Maya Ingest

`apps/maya-ingest/` runs **Prefect-orchestrated ingestion flows** that poll external sources, enrich metadata, and write normalized records into the platform datastore. It pairs with [[Packages/Maya Feeds]] adapters and [[Packages/Maya Graph]] entity resolution to keep discover and music features fresh without manual CSV imports.

Ingest is **optional** — enable it when running discover/feed features behind [[Platform/Maya Gateway]]. The voice dashboard alone does not require ingest workers.

## Role in the pipeline

```mermaid
flowchart LR
    subgraph external["External"]
        YT[YouTube channels]
        MUSIC[Music sources]
        VIDEO[Video intel APIs]
    end

    subgraph ingest["maya-ingest"]
        POLL[poll_music_sources]
        RESOLVE[resolve_person]
        PARSE[parse_video_intel]
        TASKS[embeddings / face / llm tasks]
    end

    subgraph store["Persistence"]
        FEEDS["maya-feeds normalize"]
        GRAPH["maya-graph link"]
        DB[(PostgreSQL)]
    end

    YT --> POLL
    MUSIC --> POLL
    VIDEO --> PARSE
    POLL --> FEEDS
    PARSE --> TASKS
    FEEDS --> GRAPH
    GRAPH --> DB
    RESOLVE --> GRAPH
```

## Package structure

```
apps/maya-ingest/
├── pyproject.toml
├── src/maya_ingest/
│   ├── flows/
│   │   ├── poll_music_sources.py
│   │   ├── resolve_person.py
│   │   └── parse_video_intel.py
│   └── tasks/
│       ├── yt_catalogue.py
│       ├── embeddings.py
│       ├── face.py
│       └── llm.py
└── tests/
    └── test_analyze_release.py
```

Flows compose tasks that may call LLMs for labeling, generate embeddings for similarity search, or run face detection for video intel pipelines.

## Running ingest

Ingest workers typically run as separate Prefect deployments or one-off CLI invocations — not inside the unified gateway process. Consult the repository's ingest README or Prefect deployment manifests for the current entry command (pattern):

```bash
uv sync --all-packages
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/maya

# Example: run a flow module directly (verify CLI in repo)
uv run python -m maya_ingest.flows.poll_music_sources
```

Ensure [[Packages/Maya DB]] migrations applied before first run.

## Key flows

| Flow | Purpose |
|------|---------|
| `poll_music_sources` | Scheduled poll of configured music/feed sources |
| `resolve_person` | Entity resolution for artist/person names across platforms |
| `parse_video_intel` | Extract structured intel from video metadata |

Tasks under `tasks/` provide reusable steps: YouTube catalogue maintenance (`yt_catalogue.py`), embedding generation (`embeddings.py`), optional face analysis (`face.py`), and LLM summarization (`llm.py`).

## Configuration

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Target Postgres for ingested rows |
| LLM endpoint env | Task-level summarization (`tasks/llm.py`) |
| Source-specific URLs | Music/YouTube poll targets in flow parameters |
| Prefect API URL | When using Prefect Cloud or local server |

Platform-level API keys for YouTube Data API may differ from operator Gmail OAuth — see [[Services/Google Integrations]] vs public feed enrichment.

## Data contracts

Ingest writes shapes compatible with [[Packages/Maya Contracts]] discover and registry types so `GET /api/discover/*` can rank items immediately after commit. Graph edges are written idempotently using external IDs from feed adapters.

## Troubleshooting

**Flows succeed but discover UI empty**

Verify gateway and ingest share the same `DATABASE_URL`. Check discover rank service logs in `maya_gateway/services/discover_rank.py`.

**YouTube quota exceeded**

Reduce poll frequency in Prefect schedule or add API key rotation at platform config.

**LLM task failures**

Confirm reasoning LLM reachable — same base URL family as [[Voice Runtime/LLM]] settings.

**Import errors for maya_feeds / maya_graph**

Run `uv sync --all-packages` from repo root.

**Embedding dimension errors**

Match embedding model output to pgvector column size in [[Packages/Maya DB]] migrations.

## Related documentation

- [[Packages/Maya Feeds]] — source adapters
- [[Packages/Maya Graph]] — post-ingest entity linking
- [[Platform/Maya Gateway]] — discover HTTP API
- [[Operations/Optional Services]] — enabling ingest
