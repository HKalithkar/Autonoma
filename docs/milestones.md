# Autonoma Milestones

## Slice 0: Repo Bootstrap + Dev Environment
Acceptance tests:
- `make up` brings up API, web, agent-runtime, plugin-gateway, policy, postgres, redis, otel-collector.
- `make smoke` verifies service health endpoints and OPA health.
- `make lint` and `make test` run locally.
- CI runs lint + unit tests + policy tests.

## Slice 1: Auth + RBAC + Login UI
Acceptance tests:
- OAuth/OIDC login returns valid ID/access tokens.
- RBAC denies unauthorized API calls (negative tests).
- Audit event emitted for authz allow/deny with correlation_id.

## Slice 2: Policy Guardrails + Audit
Acceptance tests:
- OPA allow/deny decision includes reasons and is logged.
- Correlation ID propagation validated across API -> policy.
- Audit entries persisted for policy decisions with redacted inputs.

## Slice 3: Workflow Registry + Plugin Gateway + HITL Approvals
Acceptance tests:
- Register/list workflows via API with schema validation.
- Trigger workflow returns run_id/job_id from plugin gateway.
- Plugin invocation audited with redacted params and policy decision.
- Risky actions create approval requests with required roles.
- Approval UI approves/denies and updates run state.

## Slice 4: Agent Runtime + Memory Stores
Acceptance tests:
- Chat-triggered run creates orchestration plan and run record.
- Short-term memory (state store) and long-term memory (vector/time-series) writes validated.
- Negative tests for disallowed tools and prompt injection attempts.
Implementation notes:
- Agent runtime exposes `/v1/agent/plan` with Redis short-term memory + long-term refs.
- API exposes `/v1/agent/runs` and `/v1/agent/configs` for LLM config overrides.
- User chat agent (`/v1/chat`) stores per-user history and executes tool calls via API.

## Slice 5: Agent Safety Gating
Acceptance tests:
- Safety eval score triggers deny or HITL path with audit entries.
Implementation notes:
- Deterministic evaluation scores stored per agent run.
- Agent approvals use `target_type=agent_run` and flow through HITL.

## Slice 6: LangGraph LLM Runtime + OpenRouter Config
Acceptance tests:
- Agent runtime uses LangGraph to produce a structured plan from LLM output.
- LLM config overrides resolve from defaults -> file -> env -> admin overrides.
- Missing or unresolved `api_key_ref` yields a safe refusal.
Implementation notes:
- OpenRouter is the default LLM provider.

## Slice 6.5: Vector Store (Weaviate/Qdrant)
Acceptance tests:
- Vector store writes long-term memory records.
- Config can switch between Weaviate and Qdrant without code changes.
Implementation notes:
- Provider-neutral schema and adapters.
- Hash embedder for dev with pluggable production embedder.

## Slice 7: GitOps Engine + Change Execution
Acceptance tests:
- Workflow run can create a GitOps change request.
- GitOps execution status is audited and visible via API/UI.
- Idempotent retry behavior validated on apply failures.
 - Memory search API and UI panel available for vector retrieval.
- Secret references (`vault:`/`gcp:`/`aws:`/`secret:`) are resolved via Plugin Gateway and audited.

## Slice 8: CI Security + Smoke Tests
Acceptance tests:
- CI includes SAST, dependency scan, container scan, OPA tests.
- `make smoke` validates login + register + run + audit trail.

## Slice 9: Observability Dashboards + Production Scaling
Acceptance tests:
- `make up` starts Prometheus and Grafana; Grafana has a provisioned datasource.
- OTEL metrics are scrapeable by Prometheus.
- Production scaling templates exist (k8s manifests with HPA + resource limits).

## Agent Runtime Rearchitecture Progress (2026-02-15)
Execution mode: one slice at a time, mandatory `make lint` + `make test` after each slice.

### Slice A: Contracts + Skeleton (Completed)
Delivered:
- Added v1 run API skeleton routes in API (`/v1/runs*`) as compatibility layer.
- Added internal policy step-evaluation endpoint scaffold.
- Added contract artifacts:
  - `docs/contracts/openapi-v1-runs.yaml`
  - `docs/contracts/events/*.schema.json` canonical runtime event schemas.
- Added contract tests:
  - `apps/contracts/tests/test_runtime_event_contracts_v1.py`
  - `apps/api/tests/test_runs_v1.py`
Verification:
- `make lint` passed.
- `make test` passed.

### Slice B: Run-Centric Persistence (Completed)
Delivered:
- Added runtime persistence tables/models:
  - `runtime_runs`, `runtime_steps`, `runtime_events`, `runtime_approvals`, `runtime_tool_invocations`.
- Added migration:
  - `apps/api/alembic/versions/0014_runtime_rearchitecture.py`
- Added repository layer:
  - `apps/api/app/runtime_store.py`
- Added tests:
  - `apps/api/tests/test_runtime_store.py`
Verification:
- `make lint` passed.
- `make test` passed.

### Slice C: Orchestrator Core (Completed)
Delivered:
- Added deployable orchestrator service:
  - `apps/runtime_orchestrator/` with Dockerfile and API.
- Orchestrator implements run lifecycle create/read/timeline and worker-step dispatch persistence.
- Event append-only flow implemented through runtime event store.
- Introduced NATS JetStream publisher scaffold (`apps/runtime_orchestrator/app/event_bus.py`).
- Introduced Temporal starter scaffold (`apps/runtime_orchestrator/app/temporal_engine.py`).
- Wired API `/v1/runs*` adapter to call orchestrator service.
- Added infra services:
  - `runtime-orchestrator`
  - `nats` (JetStream enabled)
Verification:
- `make lint` passed.
- `make test` passed.

### Slice D: Policy/Guardian Gate Enforcement (Completed)
Delivered:
- Added orchestrator policy-gate client and fail-closed decision handling in:
  - `apps/runtime_orchestrator/app/main.py`
- Enforced gate before execution transition of `reasoning_plan` step.
- Persisted `policy.decision.recorded` artifacts to `runtime_events` for all outcomes.
- Added outage fallback behavior via `RUNTIME_POLICY_FAILURE_MODE`:
  - default `pause`
  - optional `deny`
- Added internal audit artifact write for policy outcomes (`AuditEvent` with correlation/actor/tenant).
- Hardened internal policy endpoint contract in:
  - `apps/api/app/routes/runs_v1.py`
  - requires `correlation_id`, `actor_id`, `tenant_id` in request payload.
  - rejects invalid tenant/actor/correlation scope.
- Updated contract docs:
  - `docs/contracts/openapi-v1-runs.yaml`
- Added/updated tests:
  - `apps/runtime_orchestrator/tests/test_orchestrator_runs.py`
  - `apps/api/tests/test_runs_v1.py`

Verification:
- `make lint` passed.
- `make test` passed.

Security and reliability outcomes:
- no execution transition occurs without a gate decision artifact.
- policy outage path is deterministic and fails closed.
- internal gate remains service-token protected.
- tenant/actor/correlation context is validated on the gate request.

### Slice E: Execution Broker Hardening (Completed)
Delivered:
- Added orchestrator execution broker path in:
  - `apps/runtime_orchestrator/app/main.py`
- Enforced Plugin Gateway-only execution for side-effecting metadata requests.
- Added bounded retry envelope with backoff controls:
  - `RUNTIME_TOOL_MAX_RETRIES`
  - `RUNTIME_TOOL_RETRY_BACKOFF_SECONDS`
- Added normalized outcome mapping:
  - `success`
  - `transient`
  - `permanent`
  - `policy_denied`
  - `approval_required`
- Added per-attempt idempotency keys and persistence in `runtime_tool_invocations`.
- Added `RuntimeStore` helpers:
  - `get_tool_invocation`
  - `update_tool_invocation`
  - file: `apps/api/app/runtime_store.py`
- Added tool lifecycle canonical events:
  - `tool.call.started`
  - `tool.call.retrying`
  - `tool.call.completed`
  - `tool.call.failed`
- Added terminal run events from execution broker path:
  - `run.succeeded`
  - `run.failed`
- Added tests:
  - `apps/runtime_orchestrator/tests/test_orchestrator_runs.py`
    - success path
    - transient retry then success
    - policy-denied terminal failure (no retry)
  - `apps/api/tests/test_runtime_store.py`
    - tool invocation update/read helpers

Verification:
- `make lint` passed.
- `make test` passed.

Security and reliability outcomes:
- side effects flow only via Plugin Gateway adapter in orchestrator.
- retries are bounded and deterministic.
- invocation attempts are idempotency-keyed and persisted.
- non-transient failures do not retry.

### Slice F: Streaming + Timeline API Hardening (Completed)
Delivered:
- Hardened timeline API in `apps/api/app/routes/runs_v1.py`:
  - deterministic event ordering (`timestamp` + `event_id`)
  - cursor filtering with `after_event_id`
  - bounded page size with `limit`
  - response cursor field `next_event_id`
- Reworked SSE stream endpoint in `apps/api/app/routes/runs_v1.py`:
  - supports reconnect via `Last-Event-ID` header or `last_event_id` query param
  - emits SSE `id:` for each event
  - replay-first semantics, then optional live follow polling
  - live follow controls: `follow_seconds`, `poll_interval_seconds`
- Updated API contract doc:
  - `docs/contracts/openapi-v1-runs.yaml` (timeline/stream params)
- Added tests in `apps/api/tests/test_runs_v1.py`:
  - timeline ordering + cursor behavior
  - stream resume via `last_event_id` query
  - stream resume via `Last-Event-ID` header

Verification:
- `make lint` passed.
- `make test` passed.

Security and reliability outcomes:
- timeline remains tenant-scoped via orchestrator request context.
- reconnect semantics are deterministic and replay-safe.
- stream and timeline now share cursor semantics for consistent replay behavior.

### Slice G: UI Full Transparency Timeline (Completed)
Delivered:
- Added runtime timeline UI in run details modal (`apps/web/src/App.tsx`) with:
  - replay backfill from `/v1/runs/{run_id}/timeline?limit=500`
  - live stream follow from `/v1/runs/{run_id}/stream` using cursor handoff
  - event merge/dedupe and deterministic sort
- Added timeline cards for key categories:
  - policy decisions
  - tool lifecycle events
  - approval events
  - run lifecycle outcomes
- Added runtime approval actions in UI for approvers:
  - `POST /v1/runs/{run_id}/approve`
  - `POST /v1/runs/{run_id}/reject`
- Added frontend regression test:
  - `apps/web/src/App.test.tsx`
  - verifies v1 runtime timeline cards render in run detail modal.

Verification:
- `make lint` passed.
- `make test` passed.

Security and reliability outcomes:
- timeline retrieval remains behind authenticated UI flow.
- stream parsing errors are surfaced without crashing UI.
- approval actions require existing permission gate in UI.

### Slice H: Legacy Adapters + Cutover Controls (Planned)
Goal:
- Keep `/v1/chat` and `/v1/agent/plan` functional while routing execution through v1 run flow.

Impacted modules:
- `apps/api/app/routes/chat.py`
- `apps/agent_runtime/app/main.py`
- `apps/api/app/routes/agent.py`
- docs (`README.md`, `docs/agent-runtime.md`, `docs/system-design.md`)

Implementation plan:
1. Add adapter path: `/v1/chat` launches v1 run and returns compatibility summary.
2. Add adapter path for `/v1/agent/plan` to v1 orchestration where applicable.
3. Introduce feature flags for tenant/environment canary cutover.
4. Dual-write/dual-observe during verification window.
5. Define deprecation notes and removal gate for direct legacy execution.

Verification:
- regression tests for `/v0` compatibility responses.
- canary flag tests for per-tenant routing.
- smoke path covering create run -> approval -> completion -> audit/timeline.
- Required gates:

### Slice I: API/Plugin/Workflow Concurrency + Async Hardening (Completed, 2026-02-15)
Goal:
- Improve runtime path throughput for burst load (~100 concurrent requests) by removing blocking HTTP legs and adding worker/pool tuning knobs.

Impacted modules:
- `apps/plugin_gateway/app/main.py`
- `apps/plugin_gateway/tests/test_plugin_gateway_health.py`
- `apps/plugin_gateway/tests/test_plugin_gateway_invoke.py`
- `apps/workflow_adapter/app/main.py`
- `apps/workflow_adapter/tests/test_invoke.py`
- `apps/api/entrypoint.sh`
- `apps/plugin_gateway/Dockerfile`
- `apps/workflow_adapter/Dockerfile`
- `infra/docker-compose.yml`
- `.env.example`
- `docs/env-reference.md`

Delivered:
- Plugin Gateway outbound HTTP migrated to async + retry:
  - `httpx.AsyncClient`
  - transient retry/backoff preserved
  - async readiness and invoke paths
- Workflow Adapter outbound calls migrated to async:
  - secret resolver call
  - Airflow invoke
  - Jenkins invoke
- Added process concurrency knobs:
  - `API_UVICORN_WORKERS`
  - `PLUGIN_GATEWAY_UVICORN_WORKERS`
  - `WORKFLOW_ADAPTER_UVICORN_WORKERS`
- Added gateway connection-pool tuning knobs:
  - `PLUGIN_GATEWAY_HTTP_MAX_ATTEMPTS`
  - `PLUGIN_GATEWAY_HTTP_RETRY_BACKOFF_SECONDS`
  - `PLUGIN_GATEWAY_HTTP_MAX_CONNECTIONS`
  - `PLUGIN_GATEWAY_HTTP_MAX_KEEPALIVE_CONNECTIONS`
- Added managed `workflow-adapter` service in compose with healthcheck.
- Updated/added env defaults in `.env.example`.
- Updated env documentation in `docs/env-reference.md`.

Verification:
- `make lint` passed.
- `make test` passed.

Security/reliability review:
- Service token checks unchanged (default deny maintained).
- Retry remains bounded and only for transient errors.
- No direct side effects bypassing Plugin Gateway introduced.
- Audit behavior unchanged for policy/invoke paths.

### Slice J: Runtime Events Visibility in Events Tab (Completed, 2026-02-15)
Goal:
- Surface v1 runtime lifecycle/tool events in the existing Events UI feed without changing Events tab APIs.

Impacted modules:
- `apps/runtime_orchestrator/app/main.py`
- `apps/api/app/runtime_store.py`
- `apps/runtime_orchestrator/tests/test_orchestrator_runs.py`

Delivered:
- Added runtime-orchestrator mirroring from `runtime_events` writes into `event_ingests`.
- Added normalized mapping for Event feed fields:
  - `severity` by runtime event type (`info`/`medium`/`high`)
  - `status` by runtime event type/outcome
  - summary text fallback when event payload lacks `message`
- Mirrored records include correlation/tenant context and runtime event identifiers for traceability.
- Added test coverage to assert mirrored event rows are written on run creation.

Verification:
- `make lint` passed.
- `make test` passed.

Security and reliability outcomes:
- Existing authz boundaries unchanged.
- Runtime events remain append-only; mirror is additive.
- No new direct side-effect paths introduced.
  - `make lint`
  - `make test`

Security checklist:
- no bypass of policy/guardian via legacy endpoints
- no direct tool execution from chat legacy route

Handoff criteria:
- parity confirmed; legacy direct execution disabled behind controlled rollout

### Slice H: Legacy Adapters + Cutover Controls (Completed)
Delivered:
- Added shared cutover/adapter module:
  - `apps/api/app/runtime_cutover.py`
  - supports feature flags + tenant/environment canary filters.
  - supports v1 run launch helper for compatibility adapters.
- Added v1 adapter routing for legacy workflow execution and agent planning in:
  - `apps/api/app/chat_tools.py`
  - `workflow.run` can route to v1 runs via adapter.
  - `agent.plan` can route to v1 runs via adapter and return compatibility plan payload.
- Added v1 adapter routing for legacy agent run endpoint in:
  - `apps/api/app/routes/agent.py`
  - `/v1/agent/runs` can launch v1 run under feature flag and return compatibility envelope.
- Added runtime-side adapter support for:
  - `apps/agent_runtime/app/main.py`
  - `/v1/agent/plan` can route to v1 orchestrator run under canary feature flags.
- Added regression tests:
  - `apps/api/tests/test_chat.py`
  - `apps/api/tests/test_agent_runs.py`
  - `apps/agent_runtime/tests/test_agent_plans.py`

Feature flags introduced:
- `RUNTIME_V1_WORKFLOW_RUN_ADAPTER_ENABLED`
- `RUNTIME_V1_WORKFLOW_RUN_ADAPTER_CANARY_TENANTS`
- `RUNTIME_V1_WORKFLOW_RUN_ADAPTER_CANARY_ENVIRONMENTS`
- `RUNTIME_V1_AGENT_PLAN_ADAPTER_ENABLED`
- `RUNTIME_V1_AGENT_PLAN_ADAPTER_CANARY_TENANTS`
- `RUNTIME_V1_AGENT_PLAN_ADAPTER_CANARY_ENVIRONMENTS`

Verification:
- `make lint` passed.
- `make test` passed.

Security and reliability outcomes:
- legacy compatibility paths now support controlled canary cutover.
- adapter launches preserve correlation/actor/tenant context.
- service token remains required for orchestrator internal calls.

### Slice I: Runtime Rearchitecture Documentation Alignment (Completed)
Delivered:
- Updated runtime architecture docs to match delivered v1 behavior:
  - `docs/agent-runtime.md`
  - documents run-centric v1 flow, compatibility adapters, and cutover flags.
- Updated system architecture boundaries and topology:
  - `docs/system-design.md`
  - includes `runtime-orchestrator`, NATS JetStream event backbone, and durable engine model.
- Updated operator-facing README:
  - `README.md`
  - includes runtime orchestrator component, v1 run endpoints, and legacy adapter behavior.
- Updated observability guide:
  - `docs/observability.md`
  - includes v1 timeline/stream SSE APIs and runtime orchestrator metric coverage.

Verification:
- `make lint` passed.
- `make test` passed.

Security and reliability outcomes:
- docs now explicitly state plugin-gateway-only side effects and policy-first execution.
- migration/cutover controls and compatibility adapter behavior are documented for safe rollout.

### Slice J: Runtime Timeline Resilience Hotfix (Completed)
Delivered:
- Hardened orchestrator timeline serialization in:
  - `apps/runtime_orchestrator/app/main.py`
  - timeline events are now canonicalized from persisted row fields and safe defaults.
  - malformed/partial `envelope` payloads no longer cause timeline API failures.
- Added regression coverage:
  - `apps/runtime_orchestrator/tests/test_orchestrator_runs.py`
  - verifies malformed event envelope still returns a valid timeline response.

Verification:
- `make lint` passed.
- `make test` passed.

Security and reliability outcomes:
- timeline API is now robust against partial legacy data and maintains tenant-scoped metadata.
- UI runtime timeline rendering is less likely to fail due to event-shape drift.

### Slice K: Workflow Run Migration to v1 Runtime (Completed)
Delivered:
- Migrated workflow trigger endpoint to v1 orchestration:
  - `apps/api/app/routes/workflows.py`
  - `/v1/workflows/{workflow_id}/runs` now launches v1 runtime runs via orchestrator adapter.
- Preserved security handling during migration:
  - secret references are resolved before launch and only redacted params are persisted.
  - deny outcomes remain fail-closed when policy returns deny without approvals.
- Added compatibility persistence for `/v1/runs` and UI continuity:
  - workflow run rows are now keyed by runtime `run_id` for migrated runs.
  - run metadata marks adapter path (`adapter=v1_runtime`).
- Added optional status-sync hook for legacy `/v1/runs` listing:
  - `apps/api/app/routes/runs.py`
  - guarded by `RUNTIME_V1_RUN_STATUS_SYNC_ENABLED` (default disabled).
- Updated tests:
  - `apps/api/tests/test_workflows.py`
  - `apps/api/tests/test_runs_audit.py`

Verification:
- `make lint` passed.
- `make test` passed.

Security and reliability outcomes:
- workflow execution no longer performs direct plugin side effects from workflow route.
- correlation/actor/tenant context is propagated to v1 run launch.
- migrated run IDs align with runtime IDs, enabling v1 timeline access from run details.

### Slice L: Full v1 Route Cutover + Script/Doc Alignment (Completed)
Delivered:
- Hard-cut remaining run launch paths to orchestrator v1:
  - `apps/api/app/routes/agent.py`
  - `/v1/agent/runs` now always launches v1 runtime runs.
  - `apps/api/app/chat_tools.py`
  - `workflow.run`, `agent.plan`, and `approval.decision` tool flows now launch v1 runs and no longer execute legacy direct plugin paths.
  - `apps/agent_runtime/app/main.py`
  - `/v1/agent/plan` now always launches orchestrator v1.
  - `apps/api/app/routes/approvals.py`
  - removed legacy fallback execution path; workflow approval approve action dispatches via v1 runtime launch.
- Removed feature-flag canary cutover logic from API runtime cutover helper:
  - `apps/api/app/runtime_cutover.py`
  - launch helper remains, adapter-toggle helpers removed.
- Updated seed/config/script artifacts for v1-only behavior:
  - `apps/api/app/seed.py`
  - `scripts/inputs/airflow.json`
  - `scripts/inputs/jenkins.json`
  - `.env.example`
  - removed workflow-adapter-specific configuration from defaults/examples.
- Updated docs to reflect hard-cut behavior and removed stale cutover-flag guidance:
  - `docs/agent-runtime.md`
  - `docs/system-design.md`
  - `docs/workflows.md`
  - `docs/env-reference.md`
  - `README.md`

Verification:
- `make lint` passed.
- `make test` passed.

Security and reliability outcomes:
- run-producing paths now consistently propagate correlation/actor/tenant context to v1 orchestrator.
- secret ref resolution remains before workflow execution metadata dispatch.
- legacy direct workflow execution routes removed from compatibility paths to reduce bypass risk.

### Slice M: Workflow Plugin invoke_url Seed Hardening (Completed)
Delivered:
- Restored automatic workflow forward target seeding in:
  - `apps/api/app/seed.py`
  - workflow plugins (`airflow`, `jenkins`) now seed `auth_config.invoke_url` from:
    - `WORKFLOW_ADAPTER_URL` (env), default `http://workflow-adapter:9004/invoke`
- Updated setup script inputs to align with gateway expectations:
  - `scripts/inputs/airflow.json`
  - `scripts/inputs/jenkins.json`
  - both now include `auth_config.invoke_url`.
- Updated env/docs for explicit configuration:
  - `.env.example` adds `WORKFLOW_ADAPTER_URL`.
  - `docs/env-reference.md` documents `WORKFLOW_ADAPTER_URL`.

Verification:
- `make lint` passed.
- `make test` passed.

Security and reliability outcomes:
- removes bootstrap-time runtime failures caused by missing `invoke_url`.
- keeps explicit plugin-scoped forwarding config with no secret exposure changes.

### Slice N: Events/Audits Visibility for v1 Runtime Flow (Completed)
Delivered:
- Added missing workflow creation audit in chat tool path:
  - `apps/api/app/chat_tools.py`
  - `workflow.run.created` is now emitted for chat-triggered workflow runs.
- Added v1 status transition audit emission during run status sync:
  - `apps/api/app/routes/runs.py`
  - when synced status changes to terminal state, emits:
    - `workflow.run.completed` (allow)
    - `workflow.run.failed` (deny)
  - mirrored into UI Events feed through existing audit mirroring.
- Added audit emission for v1 run decision endpoints:
  - `apps/api/app/routes/runs_v1.py`
  - `/v1/runs/{run_id}/approve|reject` now emits `approval.decision`.
- Added regression tests:
  - `apps/api/tests/test_chat_tools.py`
  - `apps/api/tests/test_runs_audit.py`
  - `apps/api/tests/test_runs_v1.py`

Verification:
- `make lint` passed.
- `make test` passed.

Security and reliability outcomes:
- preserves existing RBAC gates (`approval:write`, `audit:read`).
- no secret payload expansion; audit detail remains redacted/structured.
- UI Events/Audits now receive v1 lifecycle signals expected by operators.

### Slice O: Full API/Web Endpoint Version Cutover to /v1 (Completed)
Delivered:
- Migrated API route prefixes from `/v0/*` to `/v1/*` across:
  - auth/admin/agent/audit/policy/iam/plugins/workflows/runs/approvals/secrets/chat/memory/events/gitops.
- Updated API internal endpoint references to `/v1/*` (plugin resolve, secrets resolve, audit ingest, gitops webhook, etc.).
- Migrated Web UI calls to `/v1/*` for all API interactions:
  - auth, workflows, runs, approvals, events, audits, chat, memory, IAM.
- Updated web dev proxy:
  - removed `/v0` proxy mapping.
  - `/v1` is the canonical proxied API prefix.
- Migrated scripts/docs/contracts references from `/v0/*` to `/v1/*`.
- Repository scan now reports no remaining `/v0` endpoint references.

Verification:
- `make lint` passed.
- `make test` passed.

Security and reliability outcomes:
- versioning is now consistent at `/v1` across UI/API surfaces.
- no policy/RBAC bypass introduced; route-level permission checks remain unchanged.

### Slice P: Runtime Events Feed Fallback + Stream Merge (Completed)
Delivered:
- Extended Events API to always surface runtime lifecycle events even when mirrored `event_ingests` rows are absent:
  - `apps/api/app/routes/events.py`
  - `/v1/events` now merges:
    - persisted `event_ingests`
    - fallback projections from `runtime_events` (+ `runtime_runs.environment`)
  - dedupes mirrored runtime events via `details.runtime_event_id`.
- Extended SSE events stream to include fallback runtime events:
  - `apps/api/app/routes/events.py`
  - `/v1/events/stream` now emits merged/deduped payloads from both stores.
- Added tenant scoping on event reads:
  - `EventIngest.tenant_id == ctx.tenant_id`
  - `RuntimeEvent.tenant_id == ctx.tenant_id`
- Added regression tests for runtime-only event visibility:
  - `apps/api/tests/test_event_webhook.py`
  - `test_events_list_includes_runtime_events_without_ingest`
  - `test_event_stream_once_includes_runtime_events_without_ingest`

Verification:
- `make lint` passed.
- `make test` passed.

Security and reliability outcomes:
- preserved `audit:read` RBAC gate on list/stream endpoints.
- reduced operator blind spots by ensuring runtime events remain visible despite mirror gaps.
- maintained correlation/tenant context in projected event payloads.

### Slice Q: Agent UI Run History Parity with v1 Runtime (Completed)
Goal:
- Ensure UI-created agent runs appear in Agent status/total/history and carry runtime lifecycle context.

Impacted modules:
- `apps/api/app/routes/agent.py`
- `apps/api/tests/test_agent_runs.py`

Delivered (this session):
- Persisted v1 adapter launches from `/v1/agent/runs` into `agent_runs` when runtime `run_id` is UUID.
- Added tenant scoping to `/v1/agent/runs` list query.
- Enriched `/v1/agent/runs` response with runtime-derived status and latest event metadata from:
  - `runtime_runs`
  - `runtime_events`
- Added regression tests for:
  - created run visibility in list
  - runtime status/event projection in list output

Verification:
- `make lint` passed.
- `make test` passed.

### Current Resume State (for next session)
Completed:
- Slice A, Slice B, Slice C, Slice D, Slice E, Slice F, Slice G, Slice H, Slice I, Slice J, Slice K, Slice L, Slice M, Slice N, Slice O, Slice P, Slice Q

Pending:
- None

Locked architecture decisions:
- Event backbone: NATS JetStream
- Durable engine direction: Temporal (current state is hook-only; server/UI/worker rollout pending)
- Deployment: `apps/runtime_orchestrator` as separate service
- API streaming surface: SSE exposed from `apps/api`
- Execution strategy: one slice at a time with mandatory verify gates
