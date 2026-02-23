# Agent Runtime Rearchitecture Implementation Instructions
  Version: 1.0
  Owner: Codex CLI implementation agent
  Scope: Full rearchitecture of agent runtime to durable, event-driven, security-first architecture with live UI transparency.

  ---

  ## 1) Goal

  Implement a new agent runtime architecture that:
  1. Uses durable workflow orchestration for multi-agent execution.
  2. Enforces security/policy gates before every side-effecting step.
  3. Streams real-time execution transparency to UI (agent-to-agent messages, tool calls, decisions, retries, approvals, outcomes).
  4. Preserves existing product behavior via backward-compatible adapters during migration.

  This must align with:
  - `Autonoma Intelligent Infrastructure Platform.txt`
  - `AGENTS.md` non-negotiables
  - Existing service boundaries and security rules (RBAC + OPA + audit + correlation context).

  ---

  ## 2) Locked Decisions (Do Not Re-decide)

  1. Orchestration core: **Durable workflows** (Temporal-style execution model).
  2. Default execution safety mode: **HITL on uncertainty/risk**.
  3. UI transparency level: **Full live timeline** (not summary-only).
  4. Side-effect boundary: **Plugin Gateway only** (no direct external calls from agents).
  5. Policy/guardian behavior: **default deny or pause** when policy/guardian unavailable.

  ---

  ## 3) Current-State Mapping

  Use these as migration anchors:
  - Runtime API: `apps/agent_runtime/app/main.py`, `apps/agent_runtime/app/planner.py`, `apps/agent_runtime/app/chat.py`
  - API chat/events: `apps/api/app/routes/chat.py`, `apps/api/app/routes/events.py`
  - UI: `apps/web/src/App.tsx`
  - Docs/contracts: `docs/contracts/openapi.yaml`, `docs/architecture-gap-milestones.md`, `docs/system-design.md`, `docs/agent-runtime.md`

  Current runtime is mostly synchronous and request/response. New runtime must become run-based and event-driven.

  ---

  ## 4) Required Architecture Changes

  ## 4.1 New Runtime Topology

  Create/introduce:

  1. `apps/runtime_orchestrator/`
  - Durable workflow starter and lifecycle manager.
  - Owns run state transitions and emits canonical run events.

  2. Agent worker modules/services:
  - `orchestrator_worker`
  - `security_guardian_worker`
  - `event_response_worker`
  - `reasoning_worker`
  Each worker consumes run step tasks and emits structured events.

  3. Policy/Safety Gate service boundary:
  - Every step and retry must call a guardian/policy decision endpoint.
  - No execution without explicit allow artifact.

  4. Event backbone integration:
  - Publish/consume canonical events via Kafka or NATS JetStream (choose one and stay consistent).
  - Must support replay-safe processing and idempotent consumers.

  5. Run event store:
  - Append-only event persistence for timeline/query/audit reconstruction.

  6. UI stream API:
  - SSE endpoint per run for live timeline updates.

  ## 4.2 Chat Agent Role Refit

  Chat agent must become:
  - Intent parser + run launcher + timeline narrator.
  - It must NOT execute tools/workflows directly.
  - `/v1/chat` becomes compatibility adapter that starts `v1` run and returns `run_id` + immediate summary.

  ---

  ## 5) API & Contract Work (Contract-First Mandatory)

  ## 5.1 Add New API Contracts

  Create/update OpenAPI docs (new versioned file recommended):
  - `POST /v1/runs`
  - `GET /v1/runs/{run_id}`
  - `GET /v1/runs/{run_id}/timeline`
  - `GET /v1/runs/{run_id}/stream` (SSE)
  - `POST /v1/runs/{run_id}/approve`
  - `POST /v1/runs/{run_id}/reject`
  - Internal-only policy gate endpoint for step evaluation.

  ## 5.2 Canonical Event Envelope Schema

  Add JSON schemas under `docs/contracts/events/` for at least:
  - `run.started`
  - `plan.step.proposed`
  - `agent.message.sent`
  - `policy.decision.recorded`
  - `approval.requested`
  - `approval.resolved`
  - `tool.call.started`
  - `tool.call.retrying`
  - `tool.call.completed`
  - `tool.call.failed`
  - `run.succeeded`
  - `run.failed`
  - `run.aborted`

  All events must include:
  - `event_id`, `event_type`, `schema_version`
  - `run_id`, optional `step_id`
  - `timestamp`
  - `correlation_id`, `actor_id`, `tenant_id`
  - `agent_id`
  - `payload`
  - redaction marker / visibility level

  Missing correlation/actor/tenant must fail validation.

  ---

  ## 6) Data Model Changes

  Add DB migration(s) for run-centric model (names can vary but semantics must match):
  1. `runtime_runs`
  - run identity, intent, status, requester, environment, timestamps, tenant/correlation
  2. `runtime_steps`
  - step lifecycle/status, assigned agent, gating/approval status
  3. `runtime_events` (append-only)
  - canonical event envelope storage
  4. `runtime_approvals`
  - approval workflow linkage and decision metadata
  5. `runtime_tool_invocations`
  - idempotency key, retry count, normalized outcome

  Index requirements:
  - `run_id`
  - `tenant_id + created_at`
  - `correlation_id`
  - `status`
  - unique idempotency constraints where needed.

  ---

  ## 7) Security Controls (Must Implement)

  1. Service-to-service auth required for internal endpoints.
  2. Policy/guardian unavailable => deny/pause, never auto-allow.
  3. Tool calls must include idempotency keys.
  4. Redact secrets/tokens/prompts in:
  - logs
  - traces
  - timeline payloads
  - audit events
  5. Tenant boundary checks on all read/write/query paths.
  6. Audit every allow/deny/approval/tool call with correlation metadata.

  ---

  ## 8) UI Requirements (Full Transparency)

  Update UI to render run timeline cards in real time:
  1. Agent-to-agent communications (summary messages).
  2. Decisions:
  - policy results
  - safety score/verdict
  - deny reasons / required approvals
  3. Tool lifecycle:
  - started, retries, completion/failure, latency
  4. Approval checkpoints:
  - requested, approved/rejected, by whom, when
  5. Final outcome and follow-up actions.

  The UI must consume:
  - `GET /v1/runs/{run_id}/stream` live
  - `GET /v1/runs/{run_id}/timeline` replay/backfill

  No sensitive content should be visible to unauthorized users.

  ---

  ## 9) Migration Strategy (No Breakage)

  1. Dual-path stage:
  - Keep existing `/v1/chat` and `/v1/agent/plan`.
  - Implement adapters that internally create/manage `v1` run flow.
  2. Dual-write stage:
  - Emit both legacy and new timeline/audit events for verification window.
  3. Cutover:
  - UI switches to run timeline endpoints.
  - Chat tool execution in legacy path is disabled after parity is confirmed.
  4. Deprecation:
  - Remove legacy execution paths only after tests and smoke checks pass in all environments.

  ---

  ## 10) Implementation Phases (Strict Sequence)

  ## Phase A: Contracts + skeleton
  - Add OpenAPI v1 endpoints + event schemas.
  - Add stub handlers returning deterministic placeholders.
  - Add schema contract tests.

  ## Phase B: Durable run engine
  - Introduce runtime orchestrator and worker dispatch model.
  - Persist run/step/event lifecycle.

  ## Phase C: Policy/guardian gate
  - Enforce step-level gate before each execution/retry.
  - Implement deny/pause defaults and approval routing.

  ## Phase D: Execution broker hardening
  - Add idempotency/retry envelope and normalized errors.
  - Ensure plugin gateway-only side effects.

  ## Phase E: Streaming + UI timeline
  - SSE stream + replay timeline APIs.
  - UI full timeline rendering from event stream.

  ## Phase F: Legacy adapters + cutover
  - `/v1/chat` and `/v1/agent/plan` route to `v1` run flow.
  - Roll out by environment/tenant canary.

  ---

  ## 11) Test Plan (Must Pass)

  For each phase include:

  1. Unit tests
  - workflow state transitions
  - policy gate logic
  - retry/idempotency behavior
  - redaction helpers

  2. Contract tests
  - OpenAPI request/response validation
  - Event schema validation including negative tests

  3. Integration tests
  - API -> orchestrator -> guardian -> plugin gateway -> event store -> stream

  4. Security tests
  - unauthenticated internal calls denied
  - cross-tenant data access denied
  - policy downtime => deny/pause
  - no secret leakage in logs/events

  5. UI tests
  - timeline displays agent messages/decisions/tool retries
  - approval action resumes run
  - replay + live stream consistency

  6. Resilience tests
  - worker crash/restart recovery
  - duplicate event delivery handling
  - replay idempotency

  ---

  ## 12) Verification Commands (Required Every Change)

  Per `AGENTS.md`, after each meaningful code change run:
  1. `make lint`
  2. `make test`

  Do not finish a phase without both green. If failing, fix before continuing.

  Also run targeted tests for changed services (api/runtime/web/plugin) to shorten debug loop, but final gate is still both commands above.

  ---

  ## 13) Observability Requirements

  1. OTEL traces for run lifecycle and step transitions.
  2. Trace correlation with `correlation_id`.
  3. Metrics:
  - run counts/status
  - policy allow/deny counts
  - approval latency
  - tool retries/failures
  - stream lag/throughput
  4. Dashboard updates in `docs/observability.md` and Grafana provisioning as needed.

  ---

  ## 14) Documentation Updates (Mandatory)

  Update:
  - `docs/agent-runtime.md`
  - `docs/system-design.md`
  - `docs/contracts/openapi*.yaml`
  - `docs/contracts/events/*.schema.json`
  - `README.md` (new runtime/run APIs and operator flow)
  - runbook docs for recovery/replay/troubleshooting

  Include clear migration notes and deprecation timeline for `/v0` behavior.

  ---

  ## 15) Acceptance Criteria (Definition of Done)

  All must be true:
  1. All side-effecting actions route through plugin gateway with policy/guardian decision artifacts.
  2. UI shows real-time full timeline for each run.
  3. Default HITL behavior enforced on uncertainty/risk or policy outage.
  4. Durable execution recovers from worker failure without manual DB surgery.
  5. Event schemas and APIs validated in CI.
  6. `make lint` and `make test` pass.
  7. Docs updated to match delivered behavior.

  ---

  ## 16) Anti-Patterns (Do Not Introduce)

  1. Direct tool/plugin execution from chat route.
  2. Side effects before policy/guardian check.
  3. Non-idempotent retries.
  4. Logging secrets/prompts/raw sensitive tool params.
  5. Cross-tenant query shortcuts.
  6. Unversioned event payloads.
  7. Silent fallback to allow on security subsystem failures.

  ---

  ## 17) Handoff Format for Each PR/Change Batch

  Every implementation batch must include:
  1. Goal and impacted modules.
  2. Exact files changed.
  3. Contract/API changes.
  4. Security implications and mitigations.
  5. Test evidence (`make lint`, `make test`, targeted integration results).
  6. Remaining risks and next phase entry criteria.

  ---

  ## 18) Execution Priority

  Priority order:
  1. Security correctness
  2. Durable correctness/recovery
  3. API/event contract stability
  4. UI transparency completeness
  5. Performance optimization

  Never trade security or correctness for speed.

