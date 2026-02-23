# Autonoma System Design

## Architecture Summary
Autonoma is a multi-agent control plane for infrastructure automation. It uses a
reasoning engine to plan actions, enforces security guardrails via policy and RBAC,
executes changes through a plugin gateway and GitOps, and captures all outcomes
in audit logs. The UI/API layer is the entry point for humans and external systems.

Runtime execution is run-centric:
- API exposes `/v1/runs*` contracts and SSE timeline endpoints.
- `runtime-orchestrator` owns durable run/step lifecycle transitions.
- canonical run events are persisted append-only and published via NATS JetStream.
- Temporal integration is currently a client-side starter hook only; full Temporal
  server/UI/worker deployment is pending.

## Service Boundaries
- UI (apps/web)
- API Gateway (apps/api)
- Agent Runtime (apps/agent_runtime)
- Runtime Orchestrator (apps/runtime_orchestrator)
- Plugin Gateway + Registry (apps/plugin_gateway)
- Policy (apps/policy)
- Observability + Audit (shared)
  - OTEL collector, Prometheus, Grafana dashboards
- Data Stores: Postgres, Redis, Vector DB (Weaviate/Qdrant), NATS JetStream

Plugin registry entries are categorized (`workflow`, `secret`, `mcp`, `api`, `other`)
to support discovery and policy control per integration type.

MCP server plugins are registered with `plugin_type=mcp`. The Plugin Gateway
resolves MCP metadata via the API internal resolve endpoint and forwards
JSON-RPC requests (`tools/list`, `tools/call`) to the MCP server endpoint,
including auth headers derived from the plugin auth configuration.

## Cross-Service Contract Requirements
Every request/run must carry:
- correlation_id
- actor_id
- tenant_id

All externally-effecting actions must:
- be authorized (RBAC + OPA)
- be audited (append-only)
- route side effects via the Plugin Gateway

Secrets are never stored in the API database. References use the
`secretkeyref:plugin:<name>:<path>` format and are resolved by the API through
the Plugin Gateway `resolve` action, which is policy-checked and audited without
logging the secret value.

User chat sessions and messages are stored in Postgres (per actor/tenant) to
provide context continuity across requests. Chat actions are executed through
API tools (RBAC + policy enforced). Legacy `/v1/chat` and `/v1/agent/plan`
remain compatibility adapters and launch v1 run orchestration.

Workflow invocation parameters support the same secret references. Secrets are
resolved before calling external orchestrators (Airflow/Argo/Flux/etc.) and are
redacted in stored invocation metadata.

## Memory & GitOps
- Long-term memory uses a vector store adapter (Weaviate/Qdrant) and a neutral schema.
- GitOps executions are triggered via Plugin Gateway and update runs via webhook callbacks.
