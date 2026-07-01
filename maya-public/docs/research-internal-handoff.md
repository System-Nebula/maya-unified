# Research Agent — Public → Internal Handoff

This repo (`Workspace-public`) owns the **shared research bounded context**. The internal
`~/Workspace` tree owns **operator-specific adapters** (Discord UX, Firefox history,
homelab SearXNG URLs). Internal stays downstream of public `main`; cherry-pick or merge
public commits upward, never the reverse for core agent logic.

## What lives here (upstream)

| Area | Location |
|------|----------|
| API contracts | `packages/maya-contracts/src/maya_contracts/research.py` |
| DB models + migration | `packages/maya-db/src/maya_db/models/research.py`, `migrations/versions/research_20260624.py` |
| LangGraph agent | `packages/maya-research/` |
| Gateway API | `apps/maya-gateway/src/maya_gateway/routes/research.py` |
| Prefect entry | `apps/maya-ingest/src/maya_ingest/flows/research_flow.py` |
| Discord stub | `apps/discord-shim/` (stateless proxy only) |

## Extension points (wire in internal)

Internal branches implement these; public ships null/stub defaults.

### 1. Operator browser history

**Protocol:** `maya_research.adapters.operator_history.OperatorHistoryReader`

**Public default:** `NullOperatorHistoryReader` (empty context)

**Internal should:** implement `for_research(query, window_days=30)` using
`~/Workspace/lib/sources/browser_history.py` (copies `places.sqlite` to temp, read-only).
Register at process startup:

```python
from maya_research.adapters.operator_history import OperatorHistoryReader
from maya_research.agent.nodes.firefox_reader import set_operator_history_reader

set_operator_history_reader(MyFirefoxHistoryReader())
```

Do **not** commit profile paths, `places.sqlite` copies, or operator URLs to public.

### 2. Discord progress stream

**Protocol:** `maya_research.discord.progress.ResearchProgressPublisher`

**Public default:** `NullResearchProgressPublisher`

**Internal should:** post stage updates to the Discord thread whose id was stored on the
run (`discord_thread_id`). Two integration options:

1. **SSE consumer (recommended):** subscribe to
   `GET /api/research/runs/{id}/progress` and mirror each event to the thread.
2. **Hook inside runner:** wrap `append_progress` calls with a publisher that posts to Discord.

Public gateway already persists progress events on `research_runs.progress` (JSONB).

### 3. Discord slash command + approval gate

**Public:** `apps/discord-shim` forwards `/research` to `POST /api/research/runs` and returns immediately.

**Internal should:** use the live bot (`~/Workspace/src/maya/bot/`) for:

- `/research query depth sources` — create run, open thread, start SSE mirror
- **Deep mode:** when run status is `awaiting_approval`, post the plan checklist and wait for 👍 reaction, then `POST /api/research/runs/{id}/approve`
- Final message with `artifact_url` from completed run

Approval state is **only** in the DB (`plan_approved`, `status`); reactions are a UX layer.

## Sharing streams (public contract)

### Create run

```http
POST /api/research/runs
Content-Type: application/json

{
  "brief": "Krea 2 technical analysis",
  "depth": "shallow",
  "sources": ["web", "reddit", "local", "graph"],
  "discord_thread_id": "<snowflake>",
  "operator_id": "local"
}
```

Returns `202` with `ResearchRun` body. Execution starts asynchronously.

### Progress SSE

```http
GET /api/research/runs/{run_id}/progress
```

Server-Sent Events; each line is `data: {stage, message, timestamp, details}`.
Terminal events: `{"stage":"terminal","status":"complete|failed|awaiting_approval"}`.

Poll interval on gateway: 3s. Internal Discord mirror can batch or post every event.

### Approve plan (deep mode)

```http
POST /api/research/runs/{run_id}/approve
{"approved": true}
```

Triggers execution phase only (`run_research_execution`).

### Artifact

Report markdown at `GET /api/research/artifacts/{artifact_id}` (from `artifact_url` on run).

## Env vars (public-safe examples)

See `.envrc.example`. Internal adds private values locally only:

| Variable | Public default | Internal notes |
|----------|----------------|----------------|
| `RESEARCH_SEARXNG_URL` | `http://localhost:8080/search` | Point at homelab SearXNG |
| `MAYA_ONTOLOGY_DSN` | unset | Same Postgres as music ontology |
| `LLM_API_KEY` | unset | Required for planner/synthesizer quality |
| `ARTIFACT_STORE` | `local` | `seaweed` + `SEAWEEDFS_URL` in prod |

Never commit: Firefox profile paths, Discord tokens, Reddit cookies, operator history exports.

## Cherry-pick workflow (internal downstream)

1. Land feature on public `main` (contracts → db migration → maya-research → gateway).
2. In `~/Workspace`, merge or cherry-pick the public commit range.
3. Run `uv sync --all-packages` if workspace links `Workspace-public` packages.
4. Apply internal-only wiring (bot cog, history reader, progress publisher).
5. Run `make feeds-migrate` (public Makefile) or equivalent Alembic upgrade.
6. Verify with `make research-test` in public; bot smoke test in internal.

If internal diverges, prefer **thin adapter PRs** in internal over forking `maya-research`.

## Internal counterpart

See `~/Workspace/docs/research-public-handoff.md` for bot wiring, history adapter, and SSE mirror checklist.
