# Public Boundary

This repository is limited to generic contracts, small helper packages, and
demo-safe application scaffolding.

Do not add:

- private source mappings
- collector watch configuration
- credentials or local service URLs
- generated media or datasets
- internal operations notes

## Research agent

The research bounded context is public upstream. Extension points
(`OperatorHistoryReader`, `ResearchProgressPublisher`) ship with null implementations
here; Discord UX and Firefox history wiring live in internal `~/Workspace`.

Handoff instructions: [research-internal-handoff.md](research-internal-handoff.md)

## Music domains and ingest layers

| Boundary | Owns | Does not own |
|----------|------|--------------|
| Playback | `/play` resolver, mpv, Wikidata disambiguation, `maya-graph` canonical_work lookup | Channel follows, upload notifications |
| Feeds | Follow graph, operator preferences, ingest poll, discover ranker | Stream URL extraction |
| Fetch (`packages/maya-spider`) | HTTP policy, rate limits, retries; CDP opt-in only when required | Domain parsing, ontology writes |
| Parse (`~/Workspace/lib/sources` adapters) | Per-platform normalized models | DB upserts |
| Project (`packages/maya-graph`) | `ontology_schema` DDL, `projector` upsert helpers | Raw HTTP |

Example operator follows and genre weights ship as JSON
(`packages/maya-db/migrations/data/operator_profiles_example.json`) loaded via
`make seed-profiles`. Personal crate rosters and acquisition notes belong in Vault,
not this repo.

Batch ontology enrichment runs from private `~/Workspace/lib/sources` (not
monolithic `/enrich` CLIs in public). Ingest flows call adapters then projectors.
