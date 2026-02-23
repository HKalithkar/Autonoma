# Agent Runtime (Run-Centric v1)

## Overview
Agent execution is run-centric and event-driven.
`/v1/runs*` endpoints are served from API and delegated to the
`runtime-orchestrator` service, which persists run/step/event lifecycle state
and emits canonical runtime events.

The `agent-runtime` service continues to provide planning/chat capabilities, but
legacy entrypoints (`/v1/chat`, `/v1/agent/plan`, `/v1/agent/runs`) are now
compatibility adapters that always launch v1 runs through the orchestrator.

Core runtime decisions:
- Durable orchestration: Temporal start hook is implemented in `runtime-orchestrator`
  (server/UI/worker rollout is pending).
- Event backbone: NATS JetStream for event fanout/replay-safe consumers.
- Side effects: Plugin Gateway only, never direct from agent runtime/chat route.
- Live transparency: SSE stream exposed from API at `/v1/runs/{run_id}/stream`.

Temporal rollout status (current):
- implemented: Temporal client starter hook (`apps/runtime_orchestrator/app/temporal_engine.py`).
- not yet deployed: Temporal server service in compose.
- not yet deployed: Temporal UI service in compose.
- not yet implemented: worker registration for `runtime_run_workflow`.

### Chat tool calls
The chat agent only performs actions via API tools. Tool calls are validated,
RBAC enforced, and results are returned as structured tool results in the chat
history. Supported actions include:
- `workflow.list`, `workflow.create`, `workflow.delete`, `workflow.run`
- `plugin.list`, `plugin.create`, `plugin.delete`
- `approvals.list`, `approval.get`
- `runs.list`, `run.get`
- `audit.list`, `events.list`
- `agent.plan` (compatibility adapter; launches v1 run)

Legacy direct execution paths are removed for run launch. Chat/planning calls
launch a v1 run and return compatibility payloads.

## Memory
- Short-term state: Redis, keyed by `correlation_id`.
- Long-term references: vector/time-series URIs stored as references.
- Vector content is stored in the configured vector database (Weaviate/Qdrant).

Before planning, the Orchestrator retrieves top-K relevant memory entries from
the vector store and injects them into the planning context as untrusted input.
Agent runs expose a `memory_used` flag when retrieval occurred; the UI displays
this as a small "memory" indicator in the Agent runs list.

Failed GitOps webhooks can be persisted into vector memory (`type=failure`) to
inform future planning.

## Event response coordinator
Monitoring/alert webhooks (`/v1/events/webhook`) are routed to the Event Response
Coordinator. The payload is converted to an agent plan, evaluated for safety,
and persisted as an agent run (with HITL approval when needed).
Event ingestion history is available via `GET /v1/events` (requires `audit:read`),
including a trail of policy decisions, agent planning, evaluation, and approvals.

## Endpoints
- `POST /v1/runs` (API): create orchestrated run.
- `GET /v1/runs/{run_id}` (API): fetch run summary.
- `GET /v1/runs/{run_id}/timeline` (API): replay timeline events.
- `GET /v1/runs/{run_id}/stream` (API): SSE live timeline stream.
- `POST /v1/runs/{run_id}/approve` (API): approve pending runtime step.
- `POST /v1/runs/{run_id}/reject` (API): reject pending runtime step.
- `POST /v1/agent/plan` (agent-runtime): compatibility planner that launches v1.
- `POST /v1/chat/respond` (agent-runtime): returns chat response + tool calls.
- `GET /v1/agent/configs` (API): list LLM configs (defaults + overrides).
- `PUT /v1/agent/configs/{agent_type}` (API): update LLM config overrides.
- `POST /v1/agent/runs` (API): compatibility adapter that launches v1.
- `GET /v1/agent/runs` (API): list recent agent runs with evaluation summaries.

## Adapter Behavior
Legacy adapter endpoints remain for `/v0` API compatibility, but all run launch
flows are hard-cut to orchestrator v1.

## Safety gating
Each agent run is evaluated with deterministic safety checks. Scores are computed
per run and compared against environment thresholds:
- allow: score >= approve threshold
- require approval: score between deny and approve
- deny: score < deny threshold

When a run requires approval, a HITL approval is created with `target_type=agent_run`.
Policy decisions remain authoritative and are evaluated before safety scoring.

### Score breakdown
The safety score is a 0.0–1.0 confidence measure. It starts at 1.0 and applies
penalties for risk signals:
- destructive keywords in goal: -0.5
- production environment: -0.2
- unapproved tools (not `plugin_gateway.invoke`): -0.4
- prompt injection signals in documents: -0.4

Thresholds by environment:
- dev: approve >= 0.5, deny < 0.2
- stage: approve >= 0.7, deny < 0.4
- prod: approve >= 0.9, deny < 0.7

The UI shows the final score and verdict (`allow`, `require_approval`, `deny`).

## LLM Config
LLM configs are stored as references (e.g. `api_key_ref`) and must be resolved
by the runtime via environment/secret management. Resolution order:

1. `libs/common/llm_defaults.json` base defaults.
2. `LLM_OVERRIDES_PATH` (or `LLM_CONFIG_PATH`) JSON file overrides.
3. `LLM_API_URL` and `LLM_MODEL` environment overrides (all agents).
4. Admin overrides stored in the API database (per-agent).

The runtime resolves `api_key_ref` via:
- `env:VAR_NAME` (pull from environment)
- `secretkeyref:plugin:<name>:<path>` (resolved by the API secret resolver, which
  looks up `plugin_type=secret` and calls the Plugin Gateway `resolve` action)

Invalid `api_key_ref` values are rejected by the API and agent runtime. Use only
the prefixes above.

For local development, set `LLM_API_KEY`, `LLM_API_URL`, and `LLM_MODEL` in `.env`.
If you use secret references, configure `PLUGIN_GATEWAY_TOKEN` and `SECRET_STORE_MAP`
in `.env` so the gateway can resolve the ref without logging the secret value.
The agent runtime calls the API secret resolver at `SECRET_RESOLVER_URL`
(default `http://api:8000/v1/secrets/resolve`) with the shared `SERVICE_TOKEN`.
For Vault-backed secrets, set `VAULT_ADDR`, `VAULT_TOKEN`, and `VAULT_KV_MOUNT`
and register the `vault-resolver` secret plugin.

## LLM audit logging
Agent-runtime emits `llm.call` audit events into the API audit table via
`/v1/audit/ingest`. Events are redacted and include only hashes, sizes,
latency, model, and endpoint. Raw prompts and model outputs are never stored.

Configuration:
- `AUDIT_INGEST_URL` (default: `http://api:8000/v1/audit/ingest`)
- `AUDIT_INGEST_TOKEN` (shared secret with `SERVICE_TOKEN`)
- `LLM_LOG_SUMMARY` (default false, adds a short response summary)

## Tracing (Langfuse + OTEL)
Agent-runtime emits OTEL spans for planner execution, chat handling, and LLM
invocations. LLM spans include redacted, truncated previews of inputs/outputs
plus SHA-256 hashes and character counts. Use `LLM_TRACE_PREVIEW_CHARS` to
adjust preview length. Traces are exported via the OTEL collector to Langfuse.
Set `LLM_TRACE_FULL=true` only in trusted environments to include full LLM
input/output in Langfuse OTEL attributes.

## Vector store
Agent runtime writes documents and plan summaries to a vector database for
long-term retrieval. Configuration is controlled by:
- `VECTOR_STORE_PROVIDER` (`weaviate` | `qdrant` | `disabled`)
- `VECTOR_COLLECTION`
- `WEAVIATE_URL` / `QDRANT_URL`
- `EMBEDDING_PROVIDER` (default `hash` for dev; use a real embedder in prod)

See `docs/vector-store.md` for architecture, migration, and production guidance.
