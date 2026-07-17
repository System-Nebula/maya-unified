# Maya Unified Remediation and Improvement Plan

Status: execution-ready  
Review date: 2026-07-11  
Canonical repository: C:\Users\jovan\Desktop\japeal-pkm-local\voice-agent\maya-unified  
Canonical entrypoint: launch.py -> apps/gateway/main.py  
Primary goal: preserve the excellent duplex voice experience while making the repository secure, deterministic, testable, reproducible, and safe for multiple operators.

This document is written for autonomous coding agents, including Cursor Agent, Codex, and human contributors. It contains implementation guidance, ordering constraints, expected tests, and warnings for issues that are easy to fix incorrectly.

## 1. Read This Before Editing

### 1.1 Current worktree is valuable and dirty

At review time the repository contains 20 modified tracked files and 15 untracked files. Most of the uncommitted work is the working duplex browser/Discord voice integration.

Before any agent edits code:

1. Run:

       git status --short --untracked-files=all
       git diff --stat
       git diff --check

2. Do not reset, clean, checkout, stash, or overwrite the current changes.
3. Do not delete the untracked duplex files.
4. Create a named safety branch or patch only when the user authorizes Git mutations.
5. Make each work package below independently reviewable.
6. Do not combine security containment, architecture refactoring, and voice tuning in one large patch.

### 1.2 Non-negotiable product invariants

Every implementation must preserve these behaviors:

- Models remain warm between turns.
- Browser mic ingress remains continuous and low overhead.
- TTS audio begins quickly and plays without gaps.
- Barge-in ducks quickly and only commits a smart interruption after valid speech.
- Stop, restart, reconnect, and page refresh never replay stale audio.
- One operator must never receive another operator's prompt, transcript, settings, audio, or events.
- A room guest must only receive events for the room they joined.
- No browser response may contain raw Discord, LLM, Google, webhook, or other credentials.
- The default local installation must not expose privileged endpoints to the LAN.
- Tests must not require a real GPU, microphone, Discord connection, LM Studio, Qwen3-ASR server, Blender, or paid provider unless explicitly marked.

### 1.3 Required implementation order

Follow this order:

1. Preserve and measure the current duplex baseline.
2. Contain security and cross-user disclosure bugs.
3. Repair database migration and installation blockers.
4. Introduce atomic session ownership and generation IDs.
5. Harden the audio/ASR transport.
6. Add complete CI and regression coverage.
7. Replace mutable global operator context.
8. Consolidate legacy gateways, imports, and deployment paths.

Do not start the large VoiceAgent or VoiceHub split before phases 0 through 2 have tests. Refactoring those modules first would make it difficult to distinguish existing behavior from regressions.

## 2. Current System Map

### 2.1 Runtime composition

- launch.py loads environment files and starts the unified gateway.
- apps/gateway/main.py is the real composition root.
- apps/gateway/lifespan.py seeds data, applies settings, probes integrations, and starts the voice agent.
- services/voice/hub.py adapts the legacy voice runtime to operators, rooms, SSE, settings, and gateway routes.
- packages/voice-runtime/agent.py owns conversation, LLM/tool routing, STT, TTS, memory, Discord, barge-in, playback, and session threads.
- services/voice/browser_ws.py accepts authenticated browser mic audio.
- services/voice/duplex_ingress.py performs browser endpointing and HushMic integration.
- apps/dashboard/js/mayaBrowserMic.js captures microphone PCM.
- apps/dashboard/js/mayaBrowserAudio.js schedules browser TTS PCM.
- apps/dashboard/js/mayaConversation.js owns most dashboard conversation state.

### 2.2 Existing strengths to preserve

- Raw browser PCM avoids MediaRecorder and container latency.
- Browser AudioContext scheduling uses a serialized promise chain and a short jitter lead.
- TTS streams cancellable PCM chunks.
- Models are kept warm in a long-lived agent.
- Smart barge-in ducks before ASR confirmation.
- Correlation IDs and message IDs already exist.
- There is a substantial test corpus.
- OpenTelemetry scaffolding already avoids recording prompt/audio payloads.
- The command registry and domain packages are useful extension seams.

### 2.3 Architectural problem in one sentence

The repository combines a privileged local voice assistant, multi-operator dashboard, public platform gateway, inbound webhooks, arbitrary local tools, and legacy standalone services in one process without a single enforceable trust boundary or immutable per-turn context.

## 3. Target Runtime Model

The eventual runtime should look like this:

    Browser mic
        |
        v
    authenticated connection + negotiated audio protocol
        |
        v
    bounded frame queue
        |
        v
    per-session enhancement/VAD
        |
        v
    bounded utterance queue
        |
        v
    VoiceSessionController
        |
        +--> immutable TurnContext
        |
        +--> ASR client
        |
        +--> LLM/tool worker
        |
        +--> inference arbiter
        |
        +--> TTS/audio generation
        |
        v
    audience-scoped event/audio transport
        |
        v
    one elected playback tab

The following values must be explicit objects, not inferred from mutable globals:

- Principal/operator ID
- Room ID, if any
- Audience
- Session ID
- Turn ID
- Generation ID
- Settings snapshot
- LLM client/model
- Memory store
- Personality
- Cancellation event
- Correlation ID

## 4. Work Package Ledger

Agents should update the checkbox only after implementation, tests, and acceptance criteria are complete.

### Phase 0: preservation and security containment

- [x] PRE-001 Capture the working voice baseline.
- [x] SEC-001 Default the server to loopback and define deployment profiles.
- [x] SEC-002 Make API authorization deny-by-default.
- [x] SEC-003 Protect command dispatch and dangerous capabilities.
- [x] SEC-004 Replace fail-open event audience routing.
- [x] SEC-005 Scope WebLLM requests and fulfillment.
- [x] SEC-006 Redact and separate secrets from settings.
- [x] SEC-007 Close the stored-HTML/webhook XSS chain.
- [x] SEC-008 Remove predictable bootstrap credentials and weak session secrets.
- [x] SEC-009 Authenticate or disable the Discord shim.
- [x] DB-001 Merge the two Alembic heads.

### Phase 1: voice session correctness

- [x] VOICE-001 Introduce an atomic VoiceSessionController.
- [x] VOICE-002 Add session, turn, and generation IDs to every event.
- [x] VOICE-003 Repair WebSocket replacement, reconnect, and lease cleanup.
- [x] VOICE-004 Make workers cancellable and queues bounded.
- [x] VOICE-005 Elect one browser mic/playback leader per operator.
- [x] VOICE-006 Make playback completion acknowledgment-driven.
- [x] DISCORD-001 Fix confirmed Discord VC runtime errors.
- [x] DISCORD-002 Give Discord VC one generation-aware reply task.

### Phase 2: audio and ASR transport

- [x] AUDIO-001 Add protocol negotiation and actual sample-rate handling.
- [x] AUDIO-002 Replace wall-clock VAD timing with sample-time state.
- [x] AUDIO-003 Run HushMic exactly once with isolated state.
- [x] AUDIO-004 Replace naive decimation with a real resampler.
- [x] AUDIO-005 Add browser and server backpressure.
- [x] AUDIO-006 Move browser capture from ScriptProcessor to AudioWorklet.
- [x] ASR-001 Package and pin Qwen3-ASR reproducibly.
- [x] ASR-002 Add readiness, deadlines, circuit breaking, and fallback.
- [x] ASR-003 Move blocking ASR inference off the ASGI event loop.
- [x] PERF-001 Restore true first-sentence LLM/TTS overlap behind a measured flag.

### Phase 3: quality and observability

- [ ] TEST-001 Run the complete Python test tree.
- [x] TEST-002 Add security and audience regression suites.
- [ ] TEST-003 Add deterministic duplex/session tests.
- [ ] TEST-004 Add browser audio/mic tests.
- [ ] TEST-005 Add Discord VC generation tests.
- [ ] TEST-006 Add migration-from-zero and upgrade tests.
- [ ] CI-001 Add code CI, type/lint checks, and dependency scans.
- [x] OBS-001 Add end-to-end voice latency and queue metrics.
- [ ] OBS-002 Add truthful liveness and readiness endpoints.

### Phase 4: state and architecture consolidation

- [x] CTX-001 Add a turn-wide context lock as an immediate mitigation.
- [x] CTX-002 Replace mutable global operator state with TurnContext.
- [ ] ARCH-001 Package the voice engine as a normal importable package.
- [ ] ARCH-002 Make application services depend on packages, never the reverse.
- [ ] ARCH-003 Choose one canonical gateway composition root.
- [ ] ARCH-004 Retire external Workspace fallbacks and legacy runtime paths.
- [ ] ARCH-005 Split VoiceAgent, VoiceHub, DiscordManager, and mayaConversation by responsibility.

### Phase 5: reproducible delivery and documentation

- [ ] DEV-001 Replace Windows pip installation with frozen uv synchronization.
- [ ] DEV-002 Define supported Python/CUDA profiles and optional extras.
- [ ] DEV-003 Ship a self-contained local or Postgres deployment.
- [ ] DEV-004 Repair or remove stale Docker, Compose, and systemd artifacts.
- [ ] DOC-001 Make one environment/settings schema the source of truth.
- [ ] DOC-002 Rewrite setup, STT, testing, migration, and deployment docs.
- [ ] REPO-001 Add line-ending policy, project license decision, and binary asset policy.

## 5. Detailed Fixes

## PRE-001: Preserve and Measure the Current Duplex Baseline

### Why

The browser duplex flow is already subjectively excellent. Agents are likely to "clean it up" and accidentally add buffering, model reloads, longer endpointing, or audio gaps.

### Files

- scripts/bench_stt.py
- scripts/bench_llm.py
- scripts/bench_agent_llm.py
- packages/voice-runtime/observability.py
- services/voice/duplex_ingress.py
- apps/dashboard/js/mayaBrowserAudio.js

### Implementation

Create a repeatable benchmark command that writes JSON. Use consented fixed speech fixtures, not random noise. Record:

- Input sample rate and chunk size
- Speech end to finalized utterance
- ASR duration
- Transcript to LLM first token
- LLM first token to TTS request
- TTS request to first PCM
- Speech end to first audible PCM
- Barge onset to duck
- Barge confirmation to silence
- Audio underruns
- Dropped mic frames
- WebSocket reconnects
- Event-loop lag
- Queue high-water marks

Run at least one warmup and enough repetitions to calculate p50 and p95. Store machine metadata separately from result data.

### Do not

- Do not compare ASR systems using random noise.
- Do not make hard-coded LAN addresses or model IDs part of the benchmark.
- Do not send private transcripts to telemetry.
- Do not declare fixed latency budgets until the current working baseline is captured.

### Acceptance

- One documented command produces a JSON result.
- Results distinguish cold start from warm turns.
- Later phases fail when p95 latency regresses beyond an agreed percentage.

## SEC-001: Loopback Default and Explicit Profiles

### Current bug

apps/gateway/main.py binds to 0.0.0.0 while the application includes local tools, predictable bootstrap credentials, public routes, and operator secrets.

### Recommended profiles

Add MAYA_PROFILE:

- local: default; bind 127.0.0.1; single local operator path may be allowed; do not mount public platform/webhook routes.
- operator: authenticated Postgres-backed dashboard; explicit host configuration; all privileged APIs protected.
- public: separate public-safe platform app; no voice runtime, Blender, local command execution, operator settings, or raw artifacts on the same origin.

### Code direction

In apps/gateway/main.py, honor a HOST setting:

    profile = os.getenv("MAYA_PROFILE", "local").strip().lower()
    default_host = "127.0.0.1" if profile == "local" else "0.0.0.0"
    host = os.getenv("HOST", default_host)

If profile is local and host is non-loopback, fail startup unless an explicit unsafe override is set. Do not silently warn and continue.

### Acceptance

- A default launch only listens on loopback.
- Public routes are not mounted in local profile.
- Non-loopback operator profile refuses weak credentials/secrets.

## SEC-002: Deny-by-Default HTTP and WebSocket Authorization

### Current bug

apps/gateway/main.py protects selected prefixes and then allows every other API. Adding a new router therefore creates a public endpoint unless its author remembers a separate dependency.

### Required design

Use two layers:

1. Route-level dependencies are authoritative.
2. Gateway middleware denies every API not explicitly marked public.

Create separate routers or route registries:

- public_router: health, login, first-run setup under strict conditions, signed callbacks/webhooks, explicitly public room join/read endpoints.
- operator_router: Depends(require_operator).
- admin_router: Depends(require_admin).
- service_router: signed service-to-service token or mTLS-equivalent local policy.

Do not use string-prefix matching as the only authorization model.

For the transitional middleware, use exact method plus route-template matching. Every public route should have a reason and test.

### WebSocket warning

FastAPI/Starlette HTTP middleware does not authorize WebSocket connections. Every WebSocket handler must:

- Authenticate before accept.
- Check the operator/room lease.
- Check account ban state.
- Validate Origin against configured trusted origins.
- Reject query-string session tokens unless a documented non-browser client requires them.
- Avoid logging tokens or full query strings.

### Tests

Add tests/security/test_api_auth_matrix.py. Introspect all mounted API routes and assert each one is classified as public, operator, admin, room-member, or service.

Add explicit WebSocket tests for:

- No cookie
- Invalid cookie
- Banned operator
- Wrong lease owner
- Untrusted Origin
- Expired session

### Acceptance

- Any newly added API fails closed by default.
- A route cannot become public only because its prefix was omitted.
- WebSockets have equivalent ownership enforcement.

## SEC-003: Command Dispatch and Capability Enforcement

### Current bug

apps/gateway/cmd_routes.py accepts caller-supplied operator_id. The route can reach registered commands including Blender Python execution.

### Immediate fix

Require an authenticated operator and derive identity only from the principal:

    @router.post("/dispatch")
    async def dispatch_cmd_route(
        request: Request,
        data: dict = Body(...),
        operator = Depends(require_operator),
    ) -> dict:
        operator_id = str(operator.id)

Ignore or reject payload operator_id. Only an admin-specific endpoint may act on behalf of another operator, and that action must be audited.

### Capability policy

The command model already has a permissions field. Enforce it in services/cmd/dispatcher.py before invoking the executor.

Define capabilities such as:

- command.basic
- imagine.submit
- research.run
- blender.inspect
- blender.render
- blender.execute_code
- game.control

Blender code execution must be:

- Disabled by default.
- Admin-only.
- Explicitly enabled in trusted local configuration.
- Unavailable in public and ordinary operator profiles.
- Logged with operator ID, correlation ID, action, and outcome, but not necessarily the full code if it can contain secrets.

### Difficult trap

Checking permissions only in the dashboard route is insufficient. Discord, WebLLM, internal tool loops, and the Discord shim can invoke the same dispatcher. Enforce policy in the central dispatcher.

### Acceptance

- Anonymous command dispatch returns 401.
- Caller-supplied operator_id cannot impersonate another operator.
- Ordinary operators cannot execute Blender code.
- Every surface passes through the same capability check.

## SEC-004: Exact Audience Routing

### Current bug

services/voice/hub.py uses None as a wildcard and treats audio/status/lip as globally deliverable. This leaks room and operator events.

### Required type

Introduce an explicit tagged audience:

    class AudienceKind(str, Enum):
        GLOBAL = "global"
        OPERATOR = "operator"
        ROOM = "room"

    @dataclass(frozen=True)
    class Audience:
        kind: AudienceKind
        id: str | None = None

Construction rules:

- Global must have no ID.
- Operator must have an operator ID.
- Room must have a room ID.

Matching must be exact:

    def audience_matches(subscriber: Audience, event: Audience) -> bool:
        if event.kind is AudienceKind.GLOBAL:
            return True
        return subscriber == event

Only process health/readiness and intentionally public service notices may be global. Audio, user text, assistant text, settings, status, errors, lip sync, delivery cues, WebLLM messages, tools, and playback are never global.

### Critical trap

Do not infer audience at event emission time from hub._active_operator_id or hub._active_room_id. A context switch can occur before a delayed TTS/tool event is emitted. Capture the immutable audience in TurnContext when the turn begins and attach it to every downstream event.

### Room/operator tabs

An operator participating in a room should subscribe to the room audience separately. Do not make an operator subscription implicitly receive every room event.

### Backpressure

Subscriber queues must be bounded. If an audio subscriber cannot keep up, terminate that audio subscription and require resynchronization; never silently drop a middle PCM chunk and continue as if playback is valid. Low-rate state events may be coalesced.

### Tests

Create tests/voice/test_event_audience.py with a matrix:

- Operator A event -> A only
- Operator A event -> not B
- Operator event -> not room guest
- Room X event -> X members only
- Room X event -> not room Y
- Global readiness -> all
- Audio and settings are never global

### Acceptance

- Cross-operator/room delivery tests pass.
- No code path broadcasts private events without an Audience value.

## SEC-005: Scope WebLLM Ownership

### Current bug

services/llm/webllm_broker.py stores ready clients and pending completions globally. Full messages are broadcast without an owner. Any receiver with a request ID can attempt fulfillment.

### Fix

Key all state by a connection identity:

    WebLLMClientKey(operator_id, connection_id)

Each pending request must contain:

- owner operator ID
- connection ID
- request ID
- turn ID
- generation ID
- expiration
- cancellation event

The ready endpoint must register the authenticated connection owner. The fulfill endpoint must require the same authenticated owner and connection. A request ID alone is never authorization.

Send the prompt only to the selected WebLLM client audience/connection, not general SSE.

Delete pending entries on:

- completion
- cancellation
- disconnect
- expiration
- session stop

Reject late fulfillment when generation has advanced.

### Tests

- Operator B cannot see or fulfill A's request.
- Room guest cannot see an operator WebLLM prompt.
- Old generation fulfillment is rejected.
- Disconnect cancels pending requests.
- Duplicate fulfillment is idempotently rejected.

## SEC-006: Secret-Safe Settings

### Current bug

services/settings/store.py merges environment credentials into effective settings. apps/gateway/settings_routes.py returns the merged dictionary. Settings SSE also sends the full object, and room snapshots can persist it.

### Required split

Create separate models:

- RuntimeSettings: non-secret values used by the application.
- SecretReferences: identifiers or provider keys, never browser-visible values.
- PublicSettingsResponse: safe values plus configured booleans.
- SettingsUpdateRequest: accepts new secrets but never echoes them.

Example public response:

    {
      "discord": {
        "enabled": true,
        "token_configured": true,
        "guild_id": "..."
      },
      "reasoning": {
        "provider": "litellm",
        "api_key_configured": true
      }
    }

Do not return token prefixes unless there is a demonstrated UX need.

### Placeholder trap

If a UI submits a mask such as ******** or an empty unchanged field, do not persist it as the new secret. Use an explicit operation:

- secret omitted: leave unchanged
- secret set to a real value: replace
- clear_secret true: delete

### Room snapshot trap

Room snapshots must use an allowlisted RoomVoiceSettings model. Never copy the complete settings dictionary. A room may store voice/personality/delivery identifiers, but not credentials, provider API keys, OAuth tokens, webhook secrets, local paths, or admin settings.

### Storage

Near-term:

- Atomic writes using temporary file plus replace.
- Restrictive permissions where supported.
- Central log redaction.

Long-term:

- Windows DPAPI or OS keyring for local secrets.
- Database-encrypted or external secret provider for multi-user deployment.

### Acceptance

- Browser/SSE/room APIs contain no raw secret values.
- Secret update and clear behavior is explicit and tested.
- Logs and exception payloads redact credentials.

## SEC-007: Mailgun Webhook and Stored HTML

### Current bug

apps/maya-gateway/src/maya_gateway/routes/discover_inbox.py accepts webhook data when no secret is configured, stores HTML verbatim, and serves it same-origin with scripts and same-origin enabled.

### Immediate containment

- If the webhook secret is missing, return 503 or do not mount the webhook.
- Validate signature, timestamp freshness, and replay.
- Escape body_plain before inserting it into HTML.
- Temporarily serve stored content as text/plain or attachment until sanitization is complete.

### Sanitized rendering

Use a maintained sanitizer with a strict allowlist. Strip:

- script
- iframe
- object/embed
- form/input/button
- meta refresh
- style URLs
- event attributes
- javascript/data script URLs
- SVG script-capable content

Serve artifacts from a cookieless origin if possible. If same-process serving is unavoidable, use a CSP similar to:

    sandbox; default-src 'none'; img-src https: data:; style-src 'unsafe-inline'

Do not include allow-scripts or allow-same-origin. Add X-Content-Type-Options: nosniff. Consider proxying or disabling remote images to avoid tracking.

### Replay

Mailgun timestamp verification must reject old timestamps. Persist or cache recently seen tokens/signatures for the allowed window.

### Tests

- Missing secret fails closed.
- Invalid signature fails.
- Old/replayed request fails.
- Script, event handler, javascript URL, form, and iframe payloads are removed.
- Artifact cannot fetch an authenticated API with operator cookies.

## SEC-008: Bootstrap and Session Security

### Current bug

The application creates admin/admin and signs sessions with a public fallback secret.

### Fix

- Remove unconditional default account creation.
- Use the existing first-run setup route when no operators exist.
- Alternatively generate a cryptographically random, one-use bootstrap token printed once to the local console.
- Refuse operator/public profile startup when SESSION_SECRET is missing, weak, or equal to a known example.
- Generate a random local secret into a protected data file only for loopback local profile.
- Add login throttling per IP and username.
- Rotate session on login and password change.
- Invalidate sessions after password reset or ban by including a session version in the database.
- Set Secure cookies when TLS is enabled and document reverse proxy headers.

### Difficult trap

Do not merely change admin/admin to another hard-coded password. Do not silently generate an unknown admin password and leave an unreachable account. First-run ownership must be explicit and recoverable.

### Tests

- No default credentials exist.
- Weak/missing production secret blocks startup.
- Local loopback profile can initialize safely.
- Rate limits apply without revealing whether a username exists.
- Banning/password reset invalidates old sessions.

## SEC-009: Discord Shim

### Current bug

apps/discord-shim accepts unsigned inbound interaction data and can proxy privileged commands.

### Fix

Choose one:

1. Remove/disable the shim if it is obsolete.
2. Verify Discord Ed25519 signatures over timestamp plus raw request body.
3. If it is internal glue rather than a Discord endpoint, require a rotating service token and bind only to a private interface.

It must still pass command capabilities through the central dispatcher.

## DB-001: Merge Alembic Heads

### Current bug

The current heads are:

- 20260703_msg_ids
- 20260708_browser_capture

### Fix

Create a merge-only migration:

    revision = "new_unique_merge_revision"
    down_revision = (
        "20260703_msg_ids",
        "20260708_browser_capture",
    )

    def upgrade() -> None:
        pass

    def downgrade() -> None:
        pass

Do not point one existing branch at the other after either migration may have shipped. A merge revision preserves both histories.

### Tests

- alembic heads returns exactly one head.
- Empty Postgres -> upgrade head succeeds.
- A database at each former head -> upgrade head succeeds.
- ORM metadata and expected indexes/columns match.
- Downgrade policy is documented.

## VOICE-001: Atomic VoiceSessionController

### Current bug

Voice lease reads/writes are not atomic. Stop can terminate a session even when lease release reports not owner. Session state is spread across hub fields, agent events, queues, and browser hooks.

### Required state

Create an explicit controller, preferably in services/voice/session_controller.py:

    class SessionPhase(str, Enum):
        IDLE = "idle"
        STARTING = "starting"
        LISTENING = "listening"
        TRANSCRIBING = "transcribing"
        THINKING = "thinking"
        SPEAKING = "speaking"
        STOPPING = "stopping"
        ERROR = "error"

    @dataclass
    class ActiveSession:
        session_id: UUID
        generation_id: int
        owner: Audience
        mic_source: str
        cancel: threading.Event
        phase: SessionPhase
        connection_id: UUID | None

### Start algorithm

1. Acquire the controller lock.
2. If an active session exists for a different owner, return conflict.
3. If the same owner is already active, return the current session idempotently.
4. Allocate a new session ID, generation, and cancellation event.
5. Record STARTING.
6. Release lock.
7. Apply context and start workers.
8. Reacquire lock and publish LISTENING only if the same session/generation is still current.
9. On failure, compare-and-clear only that session.

### Stop algorithm

1. Acquire lock and verify owner/admin capability.
2. Capture the current session object.
3. Mark STOPPING and increment/invalidate generation.
4. Release lock.
5. Signal cancellation, stop playback, close sockets, and join workers outside the lock.
6. Reacquire lock and clear state only if session ID still matches.

### Critical traps

- Never hold the state lock while joining a thread, awaiting network I/O, running ASR, or stopping an audio device.
- Never call agent.stop_session after an ownership check fails.
- Never clear a cancellation Event used by an old still-running worker. Each session/turn needs its own event.
- A timed-out join does not mean the worker stopped. Retain and supervise its reference.
- A late worker result must check session and generation before persistence or emission.

### Acceptance

- Concurrent starts produce one owner.
- Non-owner stop returns 403/conflict and changes nothing.
- Start during slow stop cannot inherit old queues/events.
- Late ASR/LLM/TTS results cannot enter the new session.

## VOICE-002: Session, Turn, and Generation IDs

### Current bug

The old duplex lab filters by generation_id, but the integrated path does not attach generation IDs to audio/control events.

### Required event envelope

Every event should carry:

    {
      "type": "...",
      "audience": {"kind": "operator", "id": "..."},
      "session_id": "...",
      "turn_id": "...",
      "generation_id": 42,
      "corr_id": "...",
      "sequence": 17,
      "payload": {...}
    }

Not every global readiness event needs turn fields, but all session audio/text/status/control events do.

### Client behavior

- Store current session and generation.
- Reject lower/stale generations.
- Reject audio for a different session or turn.
- audio_stop only stops matching generation.
- clear_audio advances or explicitly targets a generation.
- Reconnect performs a state synchronization before accepting audio.

### Server behavior

- Capture IDs at turn creation.
- Pass them into player/TTS callbacks.
- Check cancellation and generation before every expensive stage and before every side effect.
- Do not use mutable hub active IDs to label a delayed event.

### Acceptance

- An artificially delayed old audio chunk is ignored after restart.
- A late audio_stop cannot stop the new turn.
- Old tool/LLM results cannot be persisted to a new operator context.

## VOICE-003: WebSocket Replacement and Disconnect Cleanup

### Current bug

The disconnect hook is keyed only by operator. Registering a replacement closes the old socket, but the old socket's finally block can remove and invoke the new hook. Unexpected disconnect leaves the voice lease/session running.

### Fix

Key connections by a unique connection ID and use compare-and-remove:

    connection_id = uuid4()
    registry[operator_id] = Connection(connection_id, close_event)

    finally:
        current = registry.get(operator_id)
        if current and current.id == connection_id:
            registry.pop(operator_id, None)

Cleanup must never invoke whatever hook currently occupies the operator key.

Add:

- heartbeat/ping
- reconnect backoff
- a short disconnect grace period
- session release after grace expires without replacement
- page-unload best effort, but never rely on it
- server shutdown that closes all exact connection objects

Browser onclose must stop or mark the mic inactive and start controlled reconnect. Do not leave isActive true with a dead WebSocket.

### Acceptance

- Replacement socket remains alive after old socket finally executes.
- Brief reconnect keeps the session without duplicate workers.
- Abandoned tab eventually releases lease.
- Mic indicators match actual track/socket state.

## VOICE-004: Bounded Queues and Cancellable Workers

### Current bugs

- Turn queue is unbounded.
- SSE subscriber queues are unbounded.
- WebSocket receive pauses during ASR.
- Stop drops worker references after a timeout.
- Queue/pending text survives restart.

### Fix

Use bounded stages:

- mic frames: small bounded queue measured in milliseconds
- finalized utterances: max 1 or 2
- turns: max 1 active plus explicit pending policy
- subscriber events: bounded and typed
- TTS audio: bounded per generation

Define the overflow policy; do not rely on Queue defaults:

- Mic frames: prefer dropping old latency-building frames and reset endpoint state on a sequence gap, or close/reconnect when transport is unhealthy.
- Utterances: keep newest or reject with a visible busy signal; never silently build minutes of backlog.
- Turns: smart barge replaces/interrupts current turn; ordinary speech while busy follows a documented queue policy.
- Audio: disconnect a slow consumer rather than dropping arbitrary middle chunks.

Split WebSocket handling:

1. Receiver task reads continuously and validates frames.
2. Audio worker performs enhancement/VAD.
3. ASR worker handles finalized utterances.
4. Session controller accepts or rejects the resulting transcript by generation.

Synchronous ASR/LLM work cannot be force-cancelled safely. Use short deadlines and discard results by generation after return.

### Acceptance

- Slow ASR does not stop WebSocket reads.
- Memory remains bounded during a 30-minute soak.
- Stop/restart drains old pending work.
- Queue depth and drop/reject counts are observable.

## VOICE-005: One Mic and Playback Leader

### Current bug

Every unlocked dashboard tab can receive and play the same audio. Multiple tabs create chorus/echo and false barge-in.

### Fix

Elect one leader per operator using:

- Web Locks API when available, plus
- BroadcastChannel fallback, plus
- server-side connection role enforcement.

Roles:

- leader: mic + audio playback + playback acknowledgments
- observer: text/status UI only

The server must send high-rate audio only to the active leader connection. Leadership changes advance connection generation and synchronize state.

### Acceptance

- Two tabs show the same transcript, but only one captures/plays audio.
- Leader close transfers leadership without stale playback.

## VOICE-006: Playback Acknowledgments

### Current bug

Server completion uses fixed browser deadline/tail estimates even though the browser reports playback state.

### Fix

Send explicit acknowledgments:

- audio_queued with last sequence
- playback_started
- playback_progress or last played sequence
- playback_ended
- playback_interrupted

Key them by session/turn/generation. Add timeout fallback for dead clients, but do not add multiple stacked fixed delays.

### Acceptance

- Listening resumes from actual playback completion.
- Hidden/suspended tab timeout is handled without blocking the session forever.
- Barge-in stops the matching generation immediately.

## AUDIO-001: Audio Protocol Negotiation

### Current bug

The browser requests 48 kHz, but AudioContext and devices may use another rate. Bare binary PCM has no version, sequence, timestamp, or format.

### Initial protocol

After WebSocket authentication, server sends a challenge/session descriptor. Client responds:

    {
      "type": "audio_hello",
      "protocol": 1,
      "format": "s16le",
      "sample_rate": audioContext.sampleRate,
      "channels": 1,
      "frames_per_chunk": 2048,
      "session_id": "...",
      "generation_id": 42
    }

Server validates and sends ready only after negotiation.

Binary frames should contain at least:

- magic/version
- sequence
- sample index or capture timestamp
- flags
- PCM payload

The WebSocket connection already binds session/generation, so duplicating the full UUID in every frame is optional. Sequence and sample index are not optional.

Validate:

- even byte alignment for PCM16
- maximum frame size
- channels
- supported sample-rate range
- monotonic sequence/sample index

### Acceptance

- 44.1 and 48 kHz clients transcribe correctly.
- Gaps/reordering are detected.
- Client waits for server ready before streaming.

## AUDIO-002: Sample-Time VAD

### Current bug

Endpointing uses processing wall-clock time. When frames backlog during ASR, recorded silence processed rapidly afterward no longer represents its real duration. max_turn_ms is not enforced.

### Fix

Track sample time:

    samples_seen += frame_sample_count
    audio_ms = samples_seen * 1000.0 / sample_rate

Store speech start and last voiced positions as sample indices. Base silence, minimum speech, maximum turn, and barge onset on sample counts.

Add:

- 150 to 250 ms pre-roll ring buffer
- noise-floor calibration
- start/stop hysteresis
- sustained voiced sample count for barge onset
- enforced maximum utterance duration
- reset on sequence gap

### Barge-mode semantics

- off: never duck or interrupt; define whether speech queues or is ignored while speaking.
- instant: sustained voice immediately stops matching playback generation; ASR may follow for the next turn.
- smart: sustained voice ducks, ASR validates, then either stop/continue or unduck.

Do not calculate sustained onset from time since the first voiced frame if silence occurred between frames.

### Acceptance

- Modes match their names.
- Continuous noise cannot grow an unbounded recording.
- Backlogged processing produces the same endpoint as real-time processing.

## AUDIO-003: Exactly-Once HushMic

### Current bug

Browser frames are HushMic-enhanced before buffering, then finalized audio is enhanced again. New browser connections reset every enhancer, including Discord users.

### Recommended implementation

Use one true streaming enhancement stage:

1. Raw frame enters a per-session audio worker.
2. The session's enhancer processes it once.
3. Enhanced PCM feeds VAD and the utterance buffer.
4. Finalization only resamples; it does not call enhance again.

Alternative: buffer raw audio and enhance once at finalization. This is simpler but may add latency and makes enhanced-audio VAD unavailable. Do not mix the two approaches.

Key enhancer state by a namespaced key:

    ("browser", session_id)
    ("discord", guild_id, user_id)

Never use user ID 0 as a universal browser singleton. Never call reset(None) from a new browser connection.

Add:

- lock or one-owner worker per enhancer
- close/reset method
- LRU/TTL cleanup
- maximum enhancer count
- settings change rebuild of the singleton/factory

### Acceptance

- Test spy proves one enhancement pass per sample.
- Browser reconnect does not reset Discord enhancement.
- Enhancer dictionary remains bounded.

## AUDIO-004: Real Resampling

### Current bug

48 kHz to 16 kHz uses every third sample without an anti-alias filter. Reverse conversion repeats samples.

### Fix

Use a tested resampler such as torchaudio functional resample, soxr, or a polyphase implementation. Choose one already compatible with the supported platforms and lockfile.

Add audio golden tests:

- in-band sine amplitude
- out-of-band alias rejection
- speech SNR
- ASR transcript stability
- no clipping/DC offset

### Acceptance

- Alias energy is materially lower than naive decimation.
- Added warm-turn latency remains within the benchmark gate.

## AUDIO-005: Browser and Server Backpressure

### Browser

Do not call WebSocket.send forever without checking bufferedAmount.

Use high/low water marks and an AudioWorklet-to-main-thread bounded ring. If the high-water mark is exceeded:

- increment a drop/gap counter
- discard latency-building queued frames according to policy
- advance sequence/sample index
- notify server of a gap or reconnect

Do not accumulate old microphone audio and send it later; conversational audio values freshness over completeness.

### Server

- Bound frame and utterance queues.
- Reject oversized messages before NumPy conversion.
- Never run HushMic synchronously on the ASGI event loop.
- Track per-connection bytes/second and queue age.

### SSE

Move high-rate audio to a binary downlink WebSocket when feasible. Keep SSE for low-rate state/events. During transition, bound SSE and disconnect slow audio consumers.

## AUDIO-006: AudioWorklet

### Current bug

ScriptProcessor is deprecated and runs conversion on the main thread.

### Fix

Create an AudioWorkletProcessor that:

- reads mono input
- performs minimal float-to-PCM conversion or posts float blocks
- assigns sample offsets
- writes into a bounded SharedArrayBuffer/ring when cross-origin isolation permits
- posts chunks without allocating excessive temporary objects

Keep browser AEC/noise suppression/AGC configuration measurable; browsers may ignore constraints.

### Acceptance

- No ScriptProcessor usage remains.
- UI activity does not create mic gaps in browser tests.

## ASR-001: Reproducible Qwen3-ASR

### Current bug

Qwen3-ASR is the default but absent from pyproject/uv.lock. start-asr.ps1 installs unpinned latest code every launch.

### Fix

Add a tested, pinned asr optional extra. Do not guess a version; test and pin the selected version. Use uv to synchronize it.

Until the service is fully managed:

- Keep Whisper as the clean-install default.
- Preserve the user's current Qwen setting in their private environment/settings.
- If Qwen is selected but unavailable, fail with an actionable health response or use explicit configured fallback.

Remove runtime pip install -U.

Resolve the port collision between Qwen3-ASR and VTube Studio. Give the ASR service a dedicated configurable port.

## ASR-002: Readiness, Deadlines, and Fallback

### Client behavior

Use explicit httpx timeouts rather than one 120-second blanket timeout:

    timeout = httpx.Timeout(
        connect=1.0,
        read=configured_read_timeout,
        write=5.0,
        pool=1.0,
    )

Exact read timeout should be benchmarked, but a dead service must not freeze a turn for two minutes.

Add:

- startup/selection health probe
- circuit breaker after repeated failures
- bounded retry only for safe transient errors
- optional Whisper fallback
- clear degraded status in the dashboard
- close method for the HTTP client

Do not retry OOM or deterministic invalid-audio failures through a second expensive path automatically.

### Acceptance

- Missing ASR is detected before first speech.
- Dead service fails or falls back promptly.
- Repeated outage does not hammer the service.

## ASR-003: ASR Service Concurrency

### Current bug

scripts/asr_server.py declares an async endpoint but executes synchronous GPU inference on the event loop and reads unbounded uploads.

### Fix

- Enforce upload size and duration limits.
- Run inference in a worker thread or make the endpoint synchronous so Starlette uses its worker pool.
- Put GPU inference behind a one-job semaphore/queue.
- Keep health/readiness responsive while inference runs.
- Warm the model before readiness becomes true.
- Report queue depth and inference duration.
- Handle cancellation by discarding result; do not attempt unsafe thread termination.

## PERF-001: True First-Sentence Overlap

### Current opportunity

packages/voice-runtime/agent.py VoiceAgent._deliver buffers every sentence before speaking in both off and hybrid modes. Comments say the first sentence is fast, but LLM token generation and first-sentence TTS do not actually overlap.

### Safe implementation

Use a bounded generation-aware TTS producer/consumer:

1. sentence_chunks yields the first complete sentence.
2. Enqueue it immediately to one serial TTS worker.
3. Continue consuming LLM tokens while first-sentence TTS/playback runs.
4. For hybrid mode, collect the remainder and enqueue it as one item.
5. Every queued item includes generation and cancellation.
6. Stop drains/rejects stale items.

Do not call the same TTS engine concurrently from multiple workers.

### Difficult trap

LLM and TTS may share one GPU. Overlap can improve remote-LLM setups but hurt a same-GPU setup. Ship behind a setting and select based on measured p95/underruns, not assumptions.

## DISCORD-001: Confirmed Runtime Fixes

### Bug 1

VoiceAgent._discord_vc_sentence_wav requires part as a keyword-only argument, but Discord calls it positionally.

Fix calls to:

    self._agent._discord_vc_sentence_wav(
        text,
        instruct,
        part="first",
    )

and equivalent part="rest".

### Bug 2

VoiceAgent._emit accepts keyword arguments, but Discord passes a positional dictionary. Replace:

    self._emit(event)

with:

    self._emit(**event)

Do not let broad exception handlers hide either failure. Tests must assert emitted events and synthesized calls.

### Smart barge

Smart mode currently hard-stops at onset while logging a duck. Implement actual duck:

- instant: stop at sustained onset
- smart: reduce playback gain, transcribe, then stop or restore gain
- off: neither duck nor stop

## DISCORD-002: Generation-Aware Discord Reply Task

### Current bug

Generation is captured after compose, detached playback tasks can overlap, and audio locks are held across enhancement/write work.

### Fix

- Allocate/capture generation before compose begins.
- Check generation after ASR, after compose, before each TTS segment, and before playback.
- Keep one authoritative active reply task.
- On new valid user speech, advance generation and cancel/retire the old task.
- Do not hold receive/sink locks during HushMic, ASR, TTS, FFmpeg startup, or other blocking work.
- Use bounded PCM handoff queues.
- Ensure music protection and voice reply playback have an explicit arbitration policy.

### Acceptance

- Speech during compose prevents stale reply playback.
- Two speakers cannot create overlapping bot replies.
- DAVE receive locks remain short and measured.

## CTX-001: Immediate Turn-Wide Context Guard

### Current bug

Concurrent chat requests apply different operator settings to process-global environment, CONFIG, LLM, memory, personality, and active IDs before the inference lock begins.

### Immediate mitigation

Create one turn scheduler/lock that covers:

1. Operator/room context activation
2. Message building
3. Tool execution
4. LLM generation
5. TTS association
6. Persistence
7. Event emission registration

Do not merely lock the LLM call. The leak occurs before and after inference.

This may serialize operator turns, which is acceptable as an immediate correctness measure for one shared agent/GPU. Measure queue time separately from inference latency.

### Lock-order rule

Define and document a single order, for example:

    session state -> turn scheduler -> inference arbiter -> resource-specific lock

Never acquire the session state lock while holding a blocking resource lock. Never await browser/network work while holding a threading lock.

## CTX-002: Immutable TurnContext

### Long-term fix

Create a frozen TurnContext containing:

- principal/operator
- room/member
- Audience
- session/turn/generation
- settings snapshot
- LLM client
- memory repository
- personality
- tool capability set
- correlation IDs
- cancellation

Pass it explicitly through agent, tool, persistence, and event APIs.

Remove per-turn mutation of:

- os.environ VA_DATA_DIR
- module-global CONFIG
- hub._active_operator_id
- hub._active_room_id
- shared LLM API key/model lookup
- shared memory binding

Heavy model weights may remain shared. Per-operator state and clients must not.

## ARCH-001 and ARCH-002: Package Boundaries

### Current problem

services.paths injects package source directories into sys.path. VoiceHub subclasses the legacy HTTP server Hub. Lower-level packages import application services, creating cycles.

### Target

Create a normal importable package such as maya_voice_core under a src layout. Suggested modules:

- session.py
- context.py
- events.py
- conversation.py
- orchestration.py
- stt/base.py
- stt/whisper.py
- stt/qwen_http.py
- audio/ingress.py
- audio/enhance.py
- audio/resample.py
- tts/base.py
- tts/qwen.py
- playback.py
- memory facade
- tools facade

Move FastAPI routes and static UI out of the core package.

Dependency direction:

    apps -> services -> packages/core

Packages/core must not import apps or repository-specific services. Use protocols/interfaces and dependency injection.

### Migration approach

Use a strangler approach:

1. Add stable interfaces around current code.
2. Move one subsystem at a time.
3. Keep compatibility imports temporarily.
4. Delete legacy import paths only after callers and tests migrate.

Do not rewrite 5,000 lines in one change.

## ARCH-003 and ARCH-004: Canonical Gateway and Trust Zones

Choose apps/gateway/main.py as the canonical unified operator entrypoint unless the user explicitly chooses otherwise.

Then:

- Convert apps/maya-gateway into a router/domain package or independently deployed public app.
- Do not mount public platform mutations into the privileged local app by default.
- Remove imports from ~/Workspace and ~/Workspace/src.
- Remove the legacy voice HTTP server as a base class; keep a thin optional adapter if standalone debugging is still needed.
- Decide whether maya-bot, discord-shim, maya-ingest, and game_bridge are supported deployables or archived experiments.

Each supported deployable needs:

- explicit entrypoint
- dependency extra
- auth/trust model
- health/readiness
- tests
- deployment docs

## ARCH-005: Split God Modules Safely

### Candidate extraction order

From VoiceAgent:

1. Pure text/cue parsing functions
2. STT facade
3. delivery/TTS coordinator
4. tool intent routing
5. Discord composition
6. memory facade
7. session worker

From VoiceHub:

1. event bus
2. session controller
3. settings facade
4. conversation persistence
5. route-independent TTS rendering

From DiscordManager:

1. connection lifecycle
2. receive/utterance assembly
3. music playback
4. reply generation
5. command adapter

From mayaConversation.js:

1. API client
2. event reducer
3. persistence
4. audio/session UI
5. player
6. imagine/arena
7. room state

Add characterization tests before each extraction. Avoid line-count-only refactors.

## TEST-001: Complete Test Discovery

### Current bug

Root pytest testpaths omit many package and app suites.

### Fix

Either remove restrictive testpaths or include every supported suite:

- apps/gateway/tests
- apps/maya-gateway/tests
- apps/maya-ingest tests
- packages/maya-db/tests
- packages/maya-graph/tests
- packages/maya-image/tests
- packages/maya-research/tests
- packages/maya-spider tests
- services/browser tests
- root tests

Classify tests with markers:

- unit
- integration
- postgres
- browser
- gpu
- network
- slow

Default CI runs all CPU-safe offline tests. GPU/network jobs are explicit.

## TEST-002: Security Regression Suite

Add:

- route authorization matrix
- command capability tests
- cross-operator SSE tests
- room/guest audience tests
- WebLLM ownership tests
- settings secret redaction tests
- room snapshot allowlist tests
- webhook signature/replay/sanitization tests
- weak bootstrap/session secret tests
- Discord shim signature tests

Each discovered vulnerability in this plan needs a failing test before or in the same patch as the fix.

## TEST-003: Duplex and Session Tests

Suggested files:

- tests/voice/test_duplex_ingress.py
- tests/voice/test_voice_session_controller.py
- apps/gateway/tests/test_browser_voice_ws.py
- tests/voice/test_hushmic.py
- tests/voice/test_asr_client.py
- tests/voice/test_generation_cancellation.py
- tests/voice/test_event_backpressure.py

Required scenarios:

- silence
- short click/cough
- speech plus trailing silence
- continuous noise and max duration
- pre-roll preservation
- smart/instant/off semantics
- malformed/odd-sized frame
- sample-rate mismatch
- sequence gap
- exactly-once enhancement
- concurrent start
- non-owner stop
- reconnect replacement race
- disconnect grace
- stop during blocked ASR
- restart while old worker lives
- stale generation suppression
- bounded queue overflow
- shutdown with open WebSocket

Use fake clocks based on sample indices and fake STT/LLM/TTS implementations.

## TEST-004: Browser Tests

Establish a small testable frontend module boundary. Use Playwright and/or a lightweight JS unit runner to mock:

- MediaStream
- AudioContext
- AudioWorklet
- WebSocket
- bufferedAmount
- BroadcastChannel/Web Locks

Test:

- waits for ready
- reports actual sample rate
- backpressure behavior
- onclose clears mic state
- reconnect/backoff
- leader election
- stale generation rejection
- schedule promise rejection recovery
- matching audio_stop only
- playback acknowledgments

### Promise-chain trap

mayaBrowserAudio scheduleChain must recover after a rejected scheduling promise:

    scheduleChain = scheduleChain
        .catch(() => undefined)
        .then(() => scheduleNow(...))

Also report the error; do not silently make all later audio disappear.

## TEST-005: Discord Tests

Add tests for:

- keyword-only TTS segment calls
- event emission
- generation captured before compose
- new speech during compose
- new speech during TTS prefill
- smart duck confirm/restore
- instant stop
- off behavior
- music protection
- DAVE sink lock duration
- multiple speakers
- exactly one active bot reply

## TEST-006: Migration Tests

CI should start ephemeral Postgres and test:

- empty database upgrade
- both former heads upgrade
- current head count
- model smoke queries
- downgrade policy if supported

Do not rely only on Alembic SQL generation; execute migrations.

## CI-001: Code Quality Gate

Add workflows for:

1. Lock validation:

       uv lock --check --offline

2. Frozen install.
3. Ruff lint and format check.
4. Type checking on incrementally selected modules.
5. CPU-safe pytest.
6. Postgres migration tests.
7. Docs check/build.
8. Playwright browser tests.
9. Dependency/security scan.
10. Wheel/import smoke test.

Start coverage enforcement on critical new modules rather than demanding a high repository-wide percentage immediately.

No CI job should download multi-gigabyte GPU models unless it is an explicit cached GPU runner.

## OBS-001: Voice Observability

Create timestamps/events for:

- capture start
- speech start/end
- endpoint finalized
- ASR queued/start/end
- transcript accepted
- turn queued/start
- LLM request/first token/end
- first sentence
- TTS queued/start/first PCM/end
- first audio sent
- first audio played acknowledgment
- playback end
- barge onset/duck/confirmed/stopped/restored

Metrics:

- voice.endpoint.ms
- voice.asr.queue_ms
- voice.asr.ms
- voice.llm.ttft_ms
- voice.tts.ttfa_ms
- voice.e2e.first_audio_ms
- voice.barge.duck_ms
- voice.barge.stop_ms
- voice.frames.dropped
- voice.ws.reconnects
- voice.queue.depth
- voice.audio.underruns
- voice.generation.stale_drops

Use IDs and numeric metadata only. Do not record raw audio, prompts, transcripts, tokens, secrets, or user content by default.

## OBS-002: Liveness and Readiness

Add:

- /livez: process/event loop alive; no expensive dependency probes.
- /readyz: required profile dependencies ready.

Readiness should include:

- database/migration state when required
- voice agent load state
- selected ASR availability
- selected LLM availability or configured degraded status
- TTS availability/degraded mode
- required queues/workers

Do not always return ok true. Optional dependency failures should be represented accurately without necessarily making the whole profile unready.

## DEV-001: Frozen Windows Setup

### Current bug

setup_windows.bat invokes pip multiple times, bypasses uv workspace mappings, omits pytest/duplex, and can re-resolve huge Torch wheels.

### Fix

Use uv consistently:

    uv sync --frozen --extra dev --extra duplex

Add --extra asr only when that extra exists and is selected. Provide supported CUDA profiles rather than editing scripts manually.

Do not run pip install -U on every launch.

Add a doctor command that checks:

- Python version
- NVIDIA/CUDA/Torch
- FFmpeg
- Postgres/profile
- LM Studio/base URL
- ASR
- TTS
- microphone permissions
- ports

## DEV-002: Dependency Profiles

Define extras such as:

- dev
- voice
- gpu-cu128
- duplex
- asr
- discord
- image
- platform
- game
- mcp
- otel

Avoid making every optional GPU/platform dependency mandatory for documentation, tests, or text-only operation.

Set Python metadata to the actually supported range, for example >=3.11,<3.13 if 3.13 is not supported. Do not leave metadata and docs contradictory.

## DEV-003 and DEV-004: Deployment

Choose and document supported topologies:

### Local native profile

- Windows-first
- loopback only
- no public webhooks
- optional no-Postgres single-user implementation
- managed or clearly external ASR/LLM

### Authenticated operator profile

- Postgres required
- migrations automatic or one documented command
- strong secret validation
- explicit TLS/reverse proxy

### Public platform profile

- separate process/origin
- no privileged local tools
- signed inbound integrations
- rate limiting

Repair or remove:

- Dockerfile references to missing apps/homepage
- legacy Python 3.13 image if unsupported
- systemd paths under old Workspace directories
- embedded database credentials
- nonexistent Make targets
- Compose dependence on another checkout/external network

## DOC-001 and DOC-002: One Source of Truth

Generate or validate documentation from one settings schema where possible.

Reconcile:

- root .env.example versus packages/voice-runtime/.env.example
- root-first environment precedence
- Qwen3-ASR versus Whisper defaults
- HushMic extra/default
- Postgres requirement versus optional claims
- Python range
- CUDA cu128 versus cu124
- canonical port assignments
- canonical gateway and legacy server status
- complete test commands
- migration command
- backup/restore and secret storage

The root environment example is canonical. Nested legacy examples should be removed, generated, or explicitly labeled standalone-only.

## REPO-001: Repository Hygiene

- Add root .gitattributes to enforce intended line endings.
- Decide and add a project-level license if this is a public repository; docs/LICENSE only covers the docs framework.
- Move immutable bundled VRM/animation assets from runtime data into examples/assets, then copy on first run.
- Use Git LFS or release downloads for large optional binary assets if clone size grows.
- Keep all mutable runtime data under one canonical data directory.
- Do not write uploads/artifacts into packages or app source directories.

## 6. Difficult Issues Agents Commonly Get Wrong

### 6.1 Fixing HTTP auth but forgetting WebSockets

HTTP middleware does not secure WebSocket handshakes. Keep authentication and Origin validation in each WebSocket or a reusable WebSocket dependency.

### 6.2 Treating None as "global"

None for operator_id or room_id caused the current leak. Use a tagged Audience and exact matching. Global must be explicit.

### 6.3 Labeling delayed events from current global state

TTS/tool events can arrive after context changes. Their audience and IDs must come from the originating TurnContext.

### 6.4 Clearing a cancellation event while an old thread still runs

If stop join times out and start clears the shared event, the old worker becomes live again. Use a new cancellation event per session/turn and generation checks.

### 6.5 Holding locks around slow work

Do not hold session, sink, receive, or routing locks during ASR, LLM, TTS, HushMic, FFmpeg, HTTP, thread joins, or awaits. Capture state, release lock, do work, compare generation afterward.

### 6.6 Dropping PCM without signaling a gap

Silent frame drops corrupt VAD timing and enhancement state. Carry sequence/sample offsets and reset appropriate state on gaps.

### 6.7 Enhancing audio twice

Choose streaming enhancement or utterance enhancement. Tests must count enhancer calls/samples.

### 6.8 Assuming requested browser sample rate is actual

Read AudioContext.sampleRate and negotiate it. Device/browser constraints are hints.

### 6.9 Allowing an old socket to delete a replacement

Connection cleanup must compare connection IDs before removing registry state.

### 6.10 Using request IDs as authorization

WebLLM/job/request IDs are correlation, not ownership. Validate authenticated owner and generation.

### 6.11 Masking secrets in UI but returning them in JSON

Redaction belongs in server response models and broadcasts. Browser masking alone is not security.

### 6.12 Editing an existing Alembic branch to remove multiple heads

Create a merge revision. Rewriting history breaks deployed databases.

### 6.13 Using pip with a uv workspace

pip does not honor tool.uv.sources workspace mappings. Use uv sync --frozen.

### 6.14 Reporting healthy because optional imports were swallowed

Readiness must reflect the selected profile and selected backends. Log-and-continue is not a readiness check.

### 6.15 Making first-sentence streaming concurrent without an arbiter

One TTS engine must not be called concurrently. Use one serial generation-aware worker and benchmark shared-GPU contention.

### 6.16 Fixing operator context only around LLM inference

Context affects message building, tools, memory, settings, persistence, and event routing. Immediate lock scope must cover the entire turn.

### 6.17 Letting broad exception handlers hide contract bugs

The current Discord positional/keyword bugs are swallowed. Catch expected failures narrowly, log stack traces with IDs, and assert side effects in tests.

### 6.18 Breaking local mode while securing public mode

Define profiles explicitly. Do not solve security by forcing every local voice turn through an unavailable Postgres installation without providing a supported setup.

## 7. Agent Execution Protocol

Every Cursor/Codex agent taking a work package must:

1. State the work package ID.
2. Read this complete plan and the listed files.
3. Inspect current Git status.
4. Write or identify a failing regression test first where practical.
5. Limit edits to the package and necessary shared interfaces.
6. Preserve uncommitted user work.
7. Run the smallest relevant tests, then the broader CPU-safe suite.
8. Run git diff --check.
9. Report:

   - files changed
   - behavior changed
   - tests run and exact results
   - tests not run and why
   - security/performance implications
   - remaining risks

10. Do not mark a checkbox complete if acceptance criteria or required tests are outstanding.

### Handoff template

    Work package:
    Outcome:
    Files changed:
    Invariants preserved:
    Tests added:
    Tests executed:
    Benchmark comparison:
    Security impact:
    Known limitations:
    Next dependency:

## 8. Definition of Project-Level Done

This plan is complete only when:

- Default launch is loopback-safe.
- Privileged APIs and tools are deny-by-default.
- No default credentials or public session-secret fallback remain.
- Stored external HTML cannot execute same-origin script.
- Operator, room, WebLLM, settings, and audio isolation tests pass.
- One session controller owns lease, lifecycle, cancellation, and generation.
- Stop/restart/reconnect cannot produce stale audio or workers.
- Browser audio handles actual sample rate, gaps, and backpressure.
- HushMic is applied exactly once with isolated bounded state.
- Qwen3-ASR is pinned, managed/probed, bounded, and recoverable.
- Discord VC confirmed runtime bugs and generation races are fixed.
- Alembic has one head and migration tests pass.
- The entire supported test tree runs in CI.
- Readiness accurately reports selected dependencies.
- Current duplex warm-turn p50/p95 is preserved or improved.
- Per-operator work no longer mutates shared process-global context.
- One canonical gateway and supported deployment topology are documented.
- Clean Windows and Linux setup commands are reproducible from the lockfile.

## 9. Recommended First Three Agent Assignments

### Agent A: security containment

Take SEC-001 through SEC-004 and SEC-008. Do not touch audio algorithms. Deliver route matrix and cross-audience tests.

### Agent B: migration and reproducible setup

Take DB-001, DEV-001, ASR-001, and the minimum documentation changes. Do not change runtime ASR default until fallback/readiness behavior is explicit.

### Agent C: session-generation foundation

Take VOICE-001 through VOICE-004 with fake STT/LLM/TTS tests. Do not refactor the full VoiceAgent. Add a controller/facade around current behavior first.

After those merge, assign separate agents to audio transport, Discord VC, immutable TurnContext, CI, and architecture extraction.

## 10. Implementation Log

### 2026-07-11 - Slice 1: browser HushMic single-pass finalization

Status: implemented and focused tests passing. AUDIO-003 remains open until all input sources and concurrent-session isolation have coverage.

Files changed:

- services/voice/duplex_ingress.py
- services/voice/browser_ws.py
- tests/test_duplex_ingress.py

Behavior:

- Browser chunks continue to use the existing streaming HushMic pass before RMS/VAD.
- Finalized PCM is now resampled directly instead of being enhanced a second time.
- A browser connection resets only HushMic key 0; it no longer globally resets Discord enhancement state.
- Existing 48 kHz transport, RMS 0.015 baseline, 180 ms duck onset, 650 ms endpoint silence, 280 ms minimum utterance, and ASR call shape are unchanged.

Test evidence:

- Pre-fix regression: `pytest -q tests/test_duplex_ingress.py` -> 1 failed, 2 passed; failure proved finalization called the enhancer again.
- Post-fix regression: same command -> 3 passed in 0.10s.
- `node --check apps/dashboard/js/mayaBrowserAudio.js` -> passed.
- `node --check apps/dashboard/js/mayaBrowserMic.js` -> passed.
- Python compileall for services/voice with an external pycache -> passed.
- `git diff --check` for this slice -> passed.

### 2026-07-11 - Slice 2: captured generation IDs for stale-audio rejection

Status: implemented and focused tests passing. VOICE-002 remains open until session/turn IDs and the full event envelope are propagated.

Files changed:

- packages/voice-runtime/player.py
- packages/voice-runtime/agent.py
- apps/dashboard/js/mayaBrowserAudio.js
- apps/dashboard/js/mayaBrowserMic.js
- services/voice/browser_ws.py
- tests/test_stream_player_generation.py
- tests/test_browser_audio_generation.js

Behavior:

- StreamPlayer advances a monotonic generation on `stop()` and `begin_turn()`.
- Browser audio/lip/audio_begin/audio_stop events carry `generation_id`.
- `submit(..., generation_id=captured)` drops chunks after the generation advances.
- Browser playback adopts `audio_begin` / `clear_audio` / non-stale `audio_stop` generations and rejects mismatched audio chunks.
- A late `audio_stop` with a lower generation cannot stop the current turn.
- Interrupt WS `clear_audio` now includes the stop generation.

Test evidence:

- Pre-fix: `pytest -q tests/test_stream_player_generation.py` -> 3 failed (no generation API).
- Post-fix: same command + duplex ingress -> 6 passed.
- `node tests/test_browser_audio_generation.js` -> 3 passed.
- Broader voice regressions (generation + duplex + discord/tts/audience) -> 41 passed.
- `node --check` on mayaBrowserAudio.js / mayaBrowserMic.js -> passed.
- Python compileall for player/agent/browser_ws -> passed.
- `git diff --check` for this slice -> passed.

### 2026-07-11 - Slice 3: session/turn/corr envelope + stale-turn commit gate

Status: implemented and focused tests passing. VOICE-002 still open for audience routing on the envelope and client turn_id rejection; generation + session/turn stamping and commit gating are in place.

Files changed:

- services/ids.py
- services/voice/turn_context.py
- packages/voice-runtime/player.py
- packages/voice-runtime/agent.py
- services/voice/hub.py
- apps/dashboard/js/mayaBrowserAudio.js
- tests/test_turn_context.py
- tests/test_stream_player_generation.py
- tests/test_browser_audio_generation.js

Behavior:

- `start_session` allocates `session_id`; hub start response returns it.
- Each `_respond_turn` / preview / chat-TTS path captures a frozen `TurnContext` (session, turn, corr, generation) at creation.
- StreamPlayer stamps browser audio events with the begin_turn envelope.
- Agent `_emit` / `_emit_raw` attach session/turn/corr/generation/sequence without overwriting creation-time labels already on the event.
- History/memory commit is skipped when the session changed or a newer turn superseded the finishing turn.
- Browser playback rejects audio from a foreign `session_id`.

Test evidence:

- `pytest -q tests/test_turn_context.py tests/test_stream_player_generation.py tests/test_duplex_ingress.py` -> 12 passed.
- `node tests/test_browser_audio_generation.js` -> 4 passed.
- Broader voice regressions -> 47 passed.
- `node --check` on mayaBrowserAudio.js -> passed.
- Python compileall for touched modules -> passed.
- `git diff --check` for this slice -> passed.

### 2026-07-11 - Slice 4: VOICE-003 connection-id disconnect cleanup

Status: core compare-and-remove + abandon grace + browser onclose/reconnect implemented. Heartbeat/ping still open.

Files changed:

- services/voice/browser_ws.py
- apps/dashboard/js/mayaBrowserMic.js
- tests/test_browser_ws_registry.py
- tests/test_browser_mic_reconnect.js

Behavior:

- Each browser mic socket gets a unique `connection_id` in the operator registry.
- Replacement registration closes only the previous connection object.
- `finally` uses compare-and-remove and never invokes a replacement's close hook.
- Unexpected disconnect starts an 8s abandon grace; reconnect cancels it; expiry calls `hub.stop`.
- Intentional `clear_disconnect_hook` / `disconnect_all` cancel abandon and close exact connections.
- Browser `onclose` clears `micActive`, ignores stale sockets, and schedules reconnect backoff while a session is wanted.
- `isActive()` requires a live open WebSocket.

Test evidence:

- `pytest -q tests/test_browser_ws_registry.py` (+ prior voice slices) -> 15 passed in focused batch; 50 passed in broader voice suite.
- `node tests/test_browser_mic_reconnect.js` -> 3 passed.
- `node --check apps/dashboard/js/mayaBrowserMic.js` -> passed.
- Python compileall for browser_ws.py -> passed.
- `git diff --check` for this slice -> passed.

### 2026-07-11 - Slice 5: VOICE-003 heartbeat/ping + pagehide

Status: VOICE-003 acceptance items covered (compare-and-remove, grace, reconnect, heartbeat). Mark VOICE-003 done for the integrated browser mic path.

Files changed:

- services/voice/browser_ws.py
- apps/dashboard/js/mayaBrowserMic.js
- tests/test_browser_ws_heartbeat.py
- tests/test_browser_mic_reconnect.js

Behavior:

- Concurrent heartbeat task sends JSON `ping` every 15s; client replies `pong`.
- Any inbound bytes/text (including pong) refreshes `last_seen`.
- 45s without client activity closes the socket and starts abandon grace.
- `ready` advertises heartbeat interval/timeout.
- `pagehide` best-effort closes the socket without scheduling client reconnect.

Test evidence:

- `pytest -q tests/test_browser_ws_heartbeat.py` (+ registry/prior slices) -> 18 passed focused; 53 passed broader voice suite.
- `node tests/test_browser_mic_reconnect.js` -> 4 passed.
- `node --check apps/dashboard/js/mayaBrowserMic.js` -> passed.
- Python compileall for browser_ws.py -> passed.
- `git diff --check` for this slice -> passed.

### 2026-07-11 - Slice 6: VOICE-004 bounded queues + non-blocking ASR

Status: core acceptance for slow-ASR receive path and bounded turn/SSE/utterance queues. Mic-frame millisecond queue and full observability metrics UI still open.

Files changed:

- services/voice/bounded_queue.py
- services/voice/browser_ws.py
- services/voice/hub.py
- packages/voice-runtime/agent.py
- tests/test_bounded_queue.py
- tests/test_browser_ws_asr_queue.py
- tests/test_sse_bounded.py

Behavior:

- Browser WS receive loop only enqueues finalized PCM; a separate ASR worker runs transcription.
- Utterance queue max 2 with keep-newest overflow; client gets `busy`/`utterance_overflow`.
- Agent turn queue max 2 with keep-newest; stop/start drains pending turns.
- SSE subscriber queues max 256; control events drop oldest; audio backlog marks the tab slow and stops further audio to it.

Test evidence:

- Focused VOICE-004 + prior voice slices -> 24 passed.
- Broader voice suite -> 59 passed.
- Python compileall for touched modules -> passed.
- `git diff --check` for this slice -> passed.

### 2026-07-11 - Slice 7: VOICE-005 one mic/playback leader

Status: client election + server audio fanout to claimed SSE leader. Leadership transfer reclaim of mic is wired; soak testing across browsers still recommended.

Files changed:

- apps/dashboard/js/mayaVoiceLeader.js
- apps/dashboard/js/mayaBrowserAudio.js
- apps/dashboard/js/mayaBrowserMic.js
- apps/dashboard/js/mayaShell.js
- apps/dashboard/js/mayaConversation.js
- apps/dashboard/conversation.html
- services/voice/hub.py
- apps/gateway/voice_routes.py
- tests/test_audio_leader.py
- tests/test_voice_leader.js

Behavior:

- Web Locks elects one leader tab (BroadcastChannel heartbeat fallback).
- Leader plays TTS and owns the browser mic WS; observers keep text/status SSE only.
- Losing leadership stops local playback and releases the mic WS; gaining leadership reclaims mic when a session is wanted.
- SSE `sse_hello` carries `subscriber_id`; leader claims via `POST /api/voice/agent/audio-leader`.
- Hub sends audio/lip only to the claimed leader subscriber (all tabs until first claim, for compatibility).

Test evidence:

- `pytest -q tests/test_audio_leader.py` (+ related) -> passed in 62-test broader voice suite.
- `node tests/test_voice_leader.js` -> 2 passed.
- `node --check` on leader/audio/mic/shell -> passed.
- `git diff --check` for this slice -> passed.

### 2026-07-11 - Slice 8: VOICE-006 playback acknowledgments

Status: ack-driven browser idle with single fallback timer. Hidden-tab soak still worth manual check.

Files changed:

- packages/voice-runtime/player.py
- apps/dashboard/js/mayaBrowserAudio.js
- apps/dashboard/js/mayaBrowserMic.js
- services/voice/browser_ws.py
- tests/test_playback_acks.py

Behavior:

- Browser audio chunks carry monotonic `sequence`; server also emits `audio_queued`.
- Leader client sends `playback_started` / `playback_progress` / `playback_ended` / `playback_interrupted` over the mic WS.
- `StreamPlayer.note_playback_ack` clears idle on matching `playback_ended` (listening resumes from real completion).
- One replaceable fallback timer remains for dead/hidden clients (no stacked fixed delays).
- `is_playing()` for browser sink follows ack/idle state instead of a padded deadline.

Test evidence:

- `pytest -q tests/test_playback_acks.py tests/test_stream_player_generation.py` -> 6 passed.
- Broader voice suite -> 65 passed.
- `node --check` on mayaBrowserAudio.js / mayaBrowserMic.js -> passed.
- `git diff --check` for this slice -> passed.

### Slice: AUDIO-001 — protocol negotiation + framed PCM (2026-07-11)

Files changed:

- services/voice/audio_protocol.py
- services/voice/browser_ws.py
- apps/dashboard/js/mayaBrowserMic.js
- tests/test_audio_protocol.py
- tests/test_audio_hello_ws.py
- tests/test_audio_protocol_frame.js

Behavior:

- After WS accept, server sends `audio_challenge` (formats/rates); client replies `audio_hello` with real `AudioContext.sampleRate`.
- `ready` is sent only after successful negotiation; bare PCM before hello is rejected.
- Binary frames use 16-byte MAYA header (version, flags, sequence, sample_index) + s16le payload.
- Non-48 kHz ingress is resampled to 48 kHz; sequence gaps reset duplex turn state and re-baseline frame tracking.
- Client does not stream until `ready`; reconnect re-runs challenge/hello.

Test evidence:

- `pytest -q tests/test_audio_protocol.py tests/test_audio_hello_ws.py` (+ related voice suite) -> 34 passed.
- `node tests/test_audio_protocol_frame.js` -> 3 passed; `node --check` mayaBrowserMic.js -> passed.
- `git diff --check` for this slice.

### Slice: AUDIO-002 — sample-time VAD (2026-07-11)

Files changed:

- services/voice/duplex_ingress.py
- services/voice/browser_ws.py
- tests/test_duplex_ingress.py

Behavior:

- Endpointing uses sample indices (`samples_seen`, speech start / last voice) instead of wall-clock.
- Pre-roll (~200 ms), start hysteresis, noise-floor threshold, and `max_turn_ms` cap prevent unbounded growth and click false-starts.
- Barge modes: `off` ignores mic while assistant speaks; `smart` ducks on sustained voice; `instant` interrupts playback generation.
- Sustained barge onset resets across silence (no wall-clock-from-first-voiced cheat).
- Sequence gaps call `reset_on_gap()` so silence math stays coherent.

Test evidence:

- `pytest -q tests/test_duplex_ingress.py` (+ voice suite) -> 41 passed.

### Slice: AUDIO-003 — namespaced HushMic + bounded enhancers (2026-07-11)

Files changed:

- services/voice/hushmic.py
- services/voice/duplex_ingress.py
- services/voice/browser_ws.py
- packages/voice-runtime/agent.py
- tests/test_hushmic_isolation.py
- tests/test_duplex_ingress.py

Behavior:

- Enhancer keys are namespaced: `("browser", session_id)` / `("discord", guild_id, user_id)` — never bare int 0 as a shared singleton.
- Browser reconnect resets only its browser key; `reset(None)` is ignored (use `reset_all` / settings rebuild).
- LRU + TTL + `max_enhancers` keep the enhancer map bounded; settings model/enabled changes rebuild the singleton.
- Streaming enhance once; finalize path downsamples only (single-pass spy covered).

Test evidence:

- `pytest -q tests/test_hushmic_isolation.py tests/test_duplex_ingress.py` (+ voice suite) -> 46 passed.

### Slice: AUDIO-004 — torchaudio resampling (2026-07-11)

Files changed:

- services/voice/resample.py (new)
- services/voice/hushmic.py
- services/voice/audio_protocol.py
- packages/voice-runtime/agent.py
- packages/voice-runtime/tools/discord_vc_listen.py
- tests/test_resample.py
- tests/test_discord_vc_listen.py

Behavior:

- 48→16 kHz and 16→48 kHz use `torchaudio.functional.resample` instead of `::3` / `np.repeat`.
- Ingress 44.1→48 and Discord stereo→16k share the same helper.
- Golden tests: in-band amplitude, alias rejection vs naive, DC/clip, speech-like SNR, warm latency gate.

Test evidence:

- Voice suite including `tests/test_resample.py` -> 58 passed.

### Slice: AUDIO-005 — browser/server backpressure (2026-07-11)

Files changed:

- services/voice/browser_ws.py
- services/voice/audio_protocol.py
- apps/dashboard/js/mayaBrowserMic.js
- tests/test_backpressure.py
- tests/test_browser_backpressure.js

Behavior:

- Browser checks `bufferedAmount` high/low watermarks; drops frames (advances sequence/sample index) and sends `client_gap` instead of building mic latency.
- Server receive path only validates size + enqueues; HushMic/VAD run in an audio worker via `asyncio.to_thread`.
- Mic-frame queue max 3 (keep-newest); oversized frames rejected before unpack/NumPy.
- `backpressure` events expose bytes/sec, drop counts, queue depth/age.
- SSE binary downlink and AudioWorklet remain AUDIO-006 / follow-on.

Test evidence:

- Voice suite + `tests/test_backpressure.py` -> 59 passed.
- `node tests/test_browser_backpressure.js` -> 3 passed; `node --check` mayaBrowserMic.js -> passed.

### Slice: AUDIO-006 — AudioWorklet mic capture (2026-07-11)

Files changed:

- apps/dashboard/js/mayaMicCapture.worklet.js (new)
- apps/dashboard/js/mayaBrowserMic.js
- tests/test_audio_worklet_mic.js

Behavior:

- Mic capture uses `AudioWorkletNode` (`maya-mic-capture`); PCM16 conversion runs off the main thread.
- No `ScriptProcessor` / `onaudioprocess` remains in browser mic path.
- Worklet posts transferable Int16 chunks; main thread frames/sends with existing backpressure policy.
- Applied getUserMedia settings exposed via `getCaptureSettings()` for measurability.
- SharedArrayBuffer ring deferred until COOP/COEP isolation is enabled.

Test evidence:

- `node tests/test_audio_worklet_mic.js` -> 3 passed; `node --check` on mic + worklet -> passed.

### Slice: ASR-001 — reproducible Qwen3-ASR + Whisper default (2026-07-11)

Files changed:

- packages/voice-runtime/config.py
- packages/voice-runtime/stt.py
- services/settings/schema.py
- scripts/start-asr.ps1
- scripts/asr_server.py
- scripts/requirements-asr.txt (new)
- scripts/bench_stt.py
- tests/test_asr_001.py
- .gitignore

Behavior:

- Clean-install STT default is Whisper (`VA_STT_BACKEND=whisper`); settings schema matches.
- Qwen3-ASR HTTP server defaults to port **8091** (VTS keeps 8001).
- `start-asr.ps1` no longer `pip install -U`; uses pinned `scripts/requirements-asr.txt` in dedicated `.venv-asr` (transformers pin conflicts with main TTS venv).
- Selecting Qwen probes `/health` and fails with an actionable message if the server is down.
- Existing operator settings that already select Qwen are preserved (env/settings override defaults).

Test evidence:

- `pytest -q tests/test_asr_001.py` -> 8 passed.

### Slice: ASR-002 — timeouts, circuit breaker, Whisper fallback (2026-07-11)

Files changed:

- packages/voice-runtime/stt.py
- packages/voice-runtime/config.py
- packages/voice-runtime/agent.py
- tests/test_asr_002.py
- tests/test_asr_001.py

Behavior:

- Qwen HTTP client uses split `httpx.Timeout` (connect/read/write/pool) instead of a 120s blanket.
- Circuit breaker opens after repeated failures and cools down before retrying.
- Transient errors retry once; 4xx/invalid-audio never retries and never auto-fallbacks.
- Optional Whisper fallback (`VA_ASR_FALLBACK_WHISPER`, default on) when Qwen is down or circuit-open.
- `close()` on HTTP client; `status()` exposes degraded state; agent emits `stt_degraded` / `stt_ready`.

Test evidence:

- `pytest -q tests/test_asr_002.py tests/test_asr_001.py` -> 17 passed.

### Slice: ASR-003 — bounded ASR server concurrency (2026-07-11)

Files changed:

- scripts/asr_server.py
- packages/voice-runtime/asr_limits.py (new)
- packages/voice-runtime/stt.py (probe prefers `/readyz`)
- tests/test_asr_003.py

Behavior:

- Upload size (default 10 MiB) and duration (default 120 s) enforced before inference.
- Transcription runs in `asyncio.to_thread` behind a one-job semaphore (GPU not shared concurrently).
- `/health` stays responsive with queue_depth / waiting / in_flight / last_inference_ms.
- `/readyz` returns 503 until model is loaded and warmed.
- Client probe prefers `/readyz` so cold models are treated as unavailable.

Test evidence:

- `pytest -q tests/test_asr_003.py tests/test_asr_002.py tests/test_asr_001.py` -> 23 passed.

### Slice: DISCORD-001 — VC runtime fixes + smart barge duck (2026-07-11)

Files changed:

- packages/voice-runtime/tools/discord_bot.py
- packages/voice-runtime/agent.py
- tests/test_discord_001.py

Behavior:

- Hybrid TTS calls use keyword-only `part="first"` / `part="rest"` (matches `_discord_vc_sentence_wav`).
- VC compose emits via `_emit(type=..., text=...)`; `_emit` also accepts a legacy positional dict.
- Barge modes: `instant` stops at onset; `smart` ducks `PCMVolumeTransformer` gain, then stops or restores after transcript; `off` neither.
- Rejected/empty STT unducks so playback gain recovers.

Test evidence:

- `pytest -q tests/test_discord_001.py` -> 7 passed.

### Slice: DISCORD-002 — generation-aware reply + short sink locks (2026-07-11)

Files changed:

- packages/voice-runtime/tools/discord_bot.py
- packages/voice-runtime/tools/discord_vc_listen.py
- tests/test_discord_002.py

Behavior:

- `_begin_vc_reply()` allocates/bumps generation **before** compose; barge or a newer turn retires stale compose/TTS/play.
- One authoritative `_vc_reply_task` via `_spawn_vc_reply_task` (cancels prior worker).
- Stream TTS handoff uses a bounded queue (maxsize=3).
- Music still wins: spoken replies never interrupt `_now_playing`.
- VC sink takes PCM under lock, runs HushMic/resample **outside** the receive lock.

Test evidence:

- `pytest -q tests/test_discord_002.py tests/test_discord_001.py tests/test_discord_vc_listen.py` -> 15 passed.

### Slice: PERF-001 — first-sentence LLM/TTS overlap (2026-07-11)

Files changed:

- packages/voice-runtime/config.py (`VA_TTS_LLM_OVERLAP`, default off)
- packages/voice-runtime/agent.py (`_deliver` / hybrid / off / serial TTS worker)
- tests/test_perf_001.py

Behavior:

- hybrid/off no longer buffer the entire LLM reply before speaking; first sentence speaks at the chunk boundary.
- `VA_TTS_LLM_OVERLAP=1` runs one serial generation-aware TTS worker so LLM token consume continues during first-sentence synth (true overlap).
- Stale generation / barge skips queued TTS items. Same-GPU setups keep the flag off until measured.

Test evidence:

- `pytest -q tests/test_perf_001.py` -> 3 passed.

### Slice: VOICE-002 — audience envelope + turn_id client gate (2026-07-11)

Files changed:

- services/voice/audience.py (new)
- services/voice/turn_context.py
- packages/voice-runtime/agent.py
- packages/voice-runtime/player.py
- services/voice/hub.py
- apps/dashboard/js/mayaBrowserAudio.js
- tests/test_turn_context.py
- tests/test_browser_audio_generation.js

Behavior:

- `Audience` tags (`global` / `operator` / `room`) captured on `TurnContext` at turn start.
- `stamp_event` and StreamPlayer envelopes attach `audience` without overwriting creation-time labels.
- Hub `_agent_event` prefers event `audience` over mutable `_active_operator_id` when routing.
- Browser playback rejects audio for a foreign `turn_id` (in addition to session/generation).

Test evidence:

- `pytest -q tests/test_turn_context.py tests/test_stream_player_generation.py tests/test_perf_001.py` -> 14 passed.
- `node tests/test_browser_audio_generation.js` -> 5 passed.

### Slice: checklist sync — VOICE-003…006 already landed (2026-07-11)

Another agent completed VOICE-003 (WS registry/heartbeat/reconnect), VOICE-004 (bounded queues), VOICE-005 (audio leader), and VOICE-006 (playback acks) with tests, but ledger checkboxes were still open. Marked `[x]` to match the implementation log (Slices 4–8).

### Slice: VOICE-001 — atomic VoiceSessionController (2026-07-11)

Files changed:

- services/voice/session_controller.py (new)
- services/voice/hub.py (start/stop ownership)
- tests/test_voice_001.py
- plan.md (VOICE-003…006 checkbox sync)

Behavior:

- `VoiceSessionController` owns STARTING → LISTENING → STOPPING with compare-and-swap session/generation and per-session cancel events.
- Same-owner start is idempotent; other-owner start returns conflict; non-owner stop is forbidden and does not call `agent.stop_session`.
- Start while STOPPING is rejected until `complete_stop`; failed start compare-and-clears only that session.
- Hub runs context/workers outside the controller lock.

Test evidence:

- `pytest -q tests/test_voice_001.py tests/test_turn_context.py tests/test_browser_ws_registry.py tests/test_audio_leader.py` -> 23 passed.

### Slice: SEC-004 — exact audience broadcast matching (2026-07-11)

Files changed:

- services/voice/audience.py (`resolve_broadcast_audience`, `should_deliver`, private/global allowlists)
- services/voice/hub.py (`broadcast` fail-closed + stamp; `_agent_event` / `_boot_broadcast`)
- tests/test_event_audience.py

Behavior:

- Private event types without a resolvable `Audience` are dropped (never treated as global).
- Only `ready` may default to global; matching uses exact `audience_matches` / `should_deliver`.
- Outbound events are stamped with `audience` so delayed consumers do not re-infer from hub mutable IDs.
- Agent fan-out prefers turn/frozen audience; boot notices scope to active operator when known.

Test evidence:

- `pytest -q tests/test_event_audience.py tests/test_voice_event_isolation.py tests/test_turn_context.py tests/test_audio_leader.py tests/test_voice_001.py` -> 35 passed.

### Slice: CTX-001 — turn-wide context scheduler (2026-07-11)

Files changed:

- services/voice/turn_scheduler.py (new)
- services/voice/hub.py (`chat_text`, `_chat_text_basic`, `chat_in_room`, chat TTS)
- tests/test_ctx_001.py

Behavior:

- `TURN_SCHEDULER` serializes operator/room context activation through message build, tools/LLM, persistence, and TTS association.
- Documented lock order: session controller → turn scheduler → inference → resource locks.
- Queue wait vs hold time recorded on the scheduler for later OBS metrics.
- Concurrent holds cannot interleave (one shared agent/GPU correctness).

Test evidence:

- `pytest -q tests/test_ctx_001.py tests/test_event_audience.py tests/test_voice_001.py` -> 21 passed.

### Slice: SEC-001 — loopback default and deployment profiles (2026-07-11)

Files changed:

- services/deployment/profile.py (new)
- services/deployment/__init__.py (new)
- apps/gateway/main.py (`validate_startup_bind`, conditional platform mounts)
- .env.example (`MAYA_PROFILE`, `HOST`, `MAYA_ALLOW_NON_LOOPBACK`)
- tests/test_sec_001.py

Behavior:

- `MAYA_PROFILE=local` (default) binds `127.0.0.1` and skips public platform/webhook and platform-auth routes.
- Local + non-loopback `HOST` fails startup unless `MAYA_ALLOW_NON_LOOPBACK=1`.
- Non-loopback binds refuse weak/placeholder `SESSION_SECRET`.
- `MAYA_PROFILE=public` is refused at startup (reserved for a separate public-safe app).

Test evidence:

- `pytest -q tests/test_sec_001.py` -> 9 passed.

### Slice: SEC-002 — deny-by-default API auth matrix (2026-07-11)

Files changed:

- services/auth/api_auth_registry.py (new; exact method+template classes + reasons)
- apps/gateway/main.py (`_auth_guard` deny-unknown `/api`; removed prefix allowlist hole)
- tests/security/test_api_auth_matrix.py

Behavior:

- Mounted `/api` routes default to operator (admin under `/api/admin…`) unless explicitly `public`, `room_member`, or `service`.
- Public access requires an exact registry entry with a reason; omitting a prefix no longer opens a route.
- Unmatched `/api` paths fall through to 404 (not treated as open handlers).
- Voice WebSocket still rejects missing/invalid session with close `4401` before accept.
- Deferred: Origin allowlist + rejecting undocumented query-string WS tokens; full router splits into public/operator/admin/service routers.

Test evidence:

- `pytest -q tests/security/test_api_auth_matrix.py tests/test_sec_001.py` -> 18 passed.

### Slice: SEC-003 — command dispatch and capability enforcement (2026-07-11)

Files changed:

- services/cmd/capabilities.py (new; role→caps, blender.execute_code env gate)
- services/cmd/dispatcher.py (central permission check)
- services/cmd/bootstrap.py (declare cmd permissions)
- services/cmd/executors/blender.py (defense-in-depth code gate + audit log)
- apps/gateway/cmd_routes.py (`require_operator`; ignore payload `operator_id`)
- .env.example (`MAYA_BLENDER_EXECUTE_CODE`)
- tests/test_sec_003.py; apps/gateway/tests/test_cmd_routes.py

Behavior:

- Anonymous `/api/cmds` returns 401; identity comes only from the session principal.
- Dispatcher enforces capabilities for every surface (chat/dashboard/Discord).
- `/blend code` requires admin + `MAYA_BLENDER_EXECUTE_CODE=1` (default off).

Test evidence:

- `pytest -q tests/test_sec_003.py tests/test_cmd_blender.py apps/gateway/tests/test_cmd_routes.py tests/security/test_api_auth_matrix.py` -> 25 passed.

### Slice: SEC-005 — WebLLM ownership scoping (2026-07-11)

Files changed:

- services/llm/webllm_broker.py (per-operator/connection ready + pending ownership)
- services/llm/webllm_bridge.py (owner/turn/generation from hub context)
- apps/gateway/voice_routes.py (ready/fulfill require auth + connection_id)
- services/voice/audience.py (`webllm_request` / `webllm_unload` private)
- services/voice/hub.py (operator-scoped ready; cancel on session stop)
- apps/dashboard/js/mayaWebLLM.js (connection_id + targeted fulfill)
- tests/test_sec_005.py

Behavior:

- Ready clients and pending requests are keyed by `(operator_id, connection_id)`.
- Fulfill requires matching owner + connection; request ID alone is not auth.
- Prompts broadcast with operator audience; room guests do not receive them.
- Stale generation and duplicate completion fulfillments are rejected.
- Disconnect (`ready=false`) and session stop cancel pending requests.

Test evidence:

- `pytest -q tests/test_sec_005.py tests/test_event_audience.py` -> 14 passed.

### Slice: SEC-006 — secret-safe settings (2026-07-11)

Files changed:

- services/settings/public.py (new; `to_public_settings`, sanitize patch, room allowlist)
- services/llm/api_keys.py (placeholder no longer clears stored keys)
- services/settings/store.py + services/operator_voice/store.py (sanitize before save)
- apps/gateway/settings_routes.py (GET/POST return public settings)
- services/voice/hub.py (SSE + get_config public)
- services/rooms/service.py + apps/gateway/room_routes.py (allowlisted/public snapshots)
- tests/test_sec_006.py

Behavior:

- Browser/SSE/config APIs expose `*_configured` flags, never raw tokens/API keys/DB URLs.
- Masked/`lm-studio` submissions leave secrets unchanged; `clear_api_key` / `clear_token` clear explicitly.
- Room snapshots store allowlisted non-secret voice settings only.

Test evidence:

- `pytest -q tests/test_sec_006.py tests/test_sec_005.py tests/test_litellm_settings.py` -> 19 passed.

### Slice: SEC-007 — Mailgun webhook + stored HTML (2026-07-11)

Files changed:

- maya_gateway/services/mailgun_webhook.py (fail-closed secret, HMAC, freshness, replay)
- maya_gateway/services/email_sanitize.py (strict HTML allowlist)
- maya_gateway/routes/discover_inbox.py (sanitize + CSP sandbox without scripts/same-origin)
- tests/test_sec_007.py; apps/maya-gateway/tests/test_discover_inbox_webhook.py

### Slice: SEC-008 — bootstrap and session security (2026-07-11)

Files changed:

- services/auth/seed.py (default seed off unless `MAYA_SEED_DEFAULT_OPERATOR=1`)
- services/auth/session.py (local secret file; session version in cookie)
- services/auth/session_version.py + login_throttle.py (new)
- services/deployment/profile.py (operator profile requires strong secret; local generates secret)
- apps/gateway/auth_routes.py (login throttle)
- services/auth/operator_store.py (bump version on password/ban)
- tests/test_sec_008.py; tests/test_sec_001.py updated

### Slice: SEC-009 — Discord shim auth-or-disable (2026-07-11)

Files changed:

- apps/discord-shim/src/discord_shim/main.py (`DISCORD_SHIM_ENABLED`, service token / Ed25519, loopback bind)
- tests/test_sec_009.py
- .env.example

Test evidence:

- `pytest -q tests/test_sec_001.py tests/test_sec_007.py tests/test_sec_008.py tests/test_sec_009.py` -> 26 passed.

### Review: Codex agent folder (2026-07-12)

Reviewed `C:\Users\jovan\Documents\Codex\2026-07-11\i-need-you-to-look-for`.

Findings:

- SEC-007 Mailgun `SERVICE` registry entry + webhook fake tests were already landed in the repo.
- Playback/turn-context hardening in the live tree is stricter than the Codex `stage_current` snapshots (keep repo versions).
- Unapplied/broken leftover: `session_controller.py` had a SyntaxError (`principal_id=…` inside a dict literal). Applied the Codex `controller_fields_repair` fix (store principals on `ActiveSession`).

### Slice: DB-001 — merge Alembic heads (2026-07-12)

Files changed:

- packages/maya-db/migrations/versions/merge_msg_ids_browser_capture_20260712.py
- tests/test_db_001.py
- services/voice/session_controller.py (syntax repair from Codex review)

Behavior:

- Single head `20260712_merge_msg_ids_browser_capture` merges `20260703_msg_ids` + `20260708_browser_capture` (empty upgrade/downgrade).

Test evidence:

- `pytest -q tests/test_db_001.py tests/test_voice_001.py tests/test_sec_007.py` -> 18 passed.

### Slice: PRE-001 — duplex latency baseline harness (2026-07-12)

Files changed:

- services/voice/baseline_schema.py
- services/voice/baseline_stats.py
- services/voice/baseline_machine.py
- scripts/bench_duplex_baseline.py
- tests/test_pre_001.py
- artifacts/baseline_results.json (stub run)
- artifacts/baseline_machine.json

Behavior:

- Documented stub CLI measures speech-end → first audible PCM with warmup/reps and p50/p95.
- Machine metadata separated from result JSON; live mode reserved.
- Percentile helper uses linear interpolation.

Test evidence:

- `pytest -q tests/test_pre_001.py` + stub CLI write to `artifacts/`.

### Slice: CTX-002 — immutable TurnContext snapshot (2026-07-12)

Files changed:

- services/voice/turn_context.py
- agent / bandcamp / game / LLM provider paths preferring turn over hub
- tests/test_ctx_002.py

Behavior:

- Frozen TurnContext snapshots operator/room/data_dir/personality/settings fingerprint at turn start.
- Mid-turn hub mutations do not rewrite the frozen snapshot for tools/LLM that honor turn ctx.
- Deferred: stop mutating `VA_DATA_DIR`/`CONFIG`; inject LLM/memory into context; remove `_active_operator_id`.

Test evidence:

- `pytest -q tests/test_pre_001.py tests/test_ctx_002.py tests/test_turn_context.py tests/test_voice_001.py` -> 26 passed.

### Slice: TEST-002 — security/audience regression suite (2026-07-12)

Files changed:

- tests/security/suite_manifest.py
- tests/security/test_regression_suite.py
- scripts/run_security_suite.py
- pyproject.toml (`security` pytest marker)

Behavior:

- Documented suite covers SEC-001…009 paths: auth matrix, cmds, SSE isolation, WebLLM, settings, Mailgun, bootstrap, Discord shim.
- Suite gate asserts modules exist and define tests; canonical cross-operator/room-guest SSE checks live under `tests/security/`.
- Run: `uv run --extra dev python scripts/run_security_suite.py`

Test evidence:

- `scripts/run_security_suite.py` -> 73 passed.

### Slice: OBS-001 — voice latency/queue metrics sink (2026-07-12)

Files changed:

- services/voice/metrics.py
- services/voice/hub.py (SSE drop / slow / queue depth)
- services/voice/session_controller.py (stale generation counter)
- services/voice/tts_stream.py (`voice.tts.ttfa_ms`)
- tests/test_obs_001.py

Behavior:

- Plan metric names + turn timeline markers; durations flush to histograms; meta strips content/secrets.
- Live hooks: SSE drops/slow disconnects/queue depth, stale `complete_start`, TTS first-PCM TTFA.
- Deferred: mark every duplex/ASR/LLM/barge stage on the hot path; OTEL export of voice.* names.

Test evidence:

- `pytest -q tests/test_obs_001.py tests/test_voice_001.py tests/test_sse_bounded.py tests/test_pre_001.py` -> 20 passed.

Next slice:

- OBS-002 liveness/readiness, or TEST-001 full Python tree.
