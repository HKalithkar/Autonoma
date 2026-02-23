# Autonoma

Autonoma is an enterprise-ready, security-first automation platform for intelligent
infrastructure. It combines a policy-guarded API, agent runtime, and plugin gateway
to orchestrate workflows with full auditability, approvals, and observability.

## Components
- Web UI: operator console for chat, workflows, plugins, approvals, audits, and memory
- API Gateway: RBAC + OPA enforcement, audit logging, workflow/run control
- Agent Runtime: planning, safety checks, memory access, and tool-safe execution
- Runtime Orchestrator: durable v1 run lifecycle engine and timeline source
- Plugin Gateway + Registry: secure invocation of external systems (workflow/MCP/secret/api)
- Policy (OPA): allow/deny with reasons and required approvals
- Keycloak (OIDC): login and role management
- Postgres: metadata + audit storage
- Redis: short-term memory and chat/session state
- Vector DB (Weaviate/Qdrant): long-term memory retrieval
- NATS JetStream: runtime event backbone (publish/replay fanout)
- Observability: OTEL collector, Prometheus, Grafana dashboards

## Quickstart
1. Copy `.env.example` to `.env` and adjust if needed.
2. `make up`
3. `make trace-up` (optional Langfuse tracing stack)
4. `make smoke`
5. Open the UI, trigger a workflow run, and review audit/events.

## Bringup + Tests
- Start services: `make up`
- Start Langfuse tracing stack: `make trace-up`
- Start workflow engines (Airflow/Jenkins/n8n): `make engines-up`
- Stop services: `make down`
- Fresh project cleanup (stop + remove project containers/volumes/images): `make cleanup`
- Fresh cleanup + global orphan prune (containers/images/all unused volumes/networks): `make cleanup ALL_ORPHANS=1`
- Full aggressive cleanup (main + trace + engines stacks, then global prune): `make cleanup-all`
- Stop Langfuse tracing stack: `make trace-down`
- Health smoke: `make smoke`
- Lint: `make lint`
- Unit tests: `make test`
- Vault integration test: `VAULT_ADDR=http://vault:8200 VAULT_TOKEN=autonoma-dev-token make test-vault`
- Policy tests: `make policy-test`
- E2E tests: `make e2e`

## Commands
- `make format`
- `make lint`
- `make test`
- `make db-migrate`
- `make dev`
- `make up` / `make down`
- `make cleanup` (project-scoped reset)
- `make cleanup ALL_ORPHANS=1` (project reset + global prune, including all unused volumes)
- `make cleanup-all` (aggressive cleanup across main/trace/engines + global prune + `--rmi all`)
- `make trace-up` / `make trace-down`
- `make engines-airflow-up`
- `make engines-jenkins-up`
- `make engines-n8n-up`
- `make engines-up` / `make engines-down`
- `make smoke`
- `make policy-test` (use `DOCKER_PLATFORM=linux/arm64/v8` on Apple Silicon)
- `make e2e`

## Local Tooling
Lint/tests run inside containers, so no local Python/Node installs are required.
URL fetches via `tools/fetch_url.py` should be run inside the devtools container:
`docker compose -f infra/docker-compose.yml run --rm devtools python tools/fetch_url.py <url>`.

## LLM config
Agent LLMs default to OpenRouter. Override defaults in two ways:
- Config file: set `LLM_OVERRIDES_PATH` (or `LLM_CONFIG_PATH`) to a JSON file that
  overrides `api_url`, `model`, and `api_key_ref` per agent.
- Admin UI/API: `PUT /v1/agent/configs/{agent_type}` stores per-agent overrides.

Use `env:LLM_API_KEY` in `api_key_ref` for environment-backed secrets. Secret
references use the format `secretkeyref:plugin:<name>:<path>` and are resolved
via the API secret resolver (which looks up a `plugin_type=secret` plugin by
name, then calls the Plugin Gateway `resolve` action). Configure
`PLUGIN_GATEWAY_TOKEN`, `SECRET_STORE_MAP`, and `SECRET_RESOLVER_URL` for dev.

## Vector store
Vector memory is stored in Weaviate by default. Configure via:
- `VECTOR_STORE_PROVIDER` (`weaviate` | `qdrant` | `disabled`)
- `WEAVIATE_URL` / `QDRANT_URL`
- `VECTOR_COLLECTION`

See `docs/vector-store.md` for architecture and migration guidance.

## GitOps
GitOps change execution is routed through the Plugin Gateway with webhook callbacks.
See `docs/gitops.md` for the flow and webhook payload.

## Observability
Prometheus + Grafana are included in the local stack. Grafana ships with a
provisioned datasource and a starter dashboard.
See `docs/observability.md`.
Langfuse runs via `make trace-up` and OTEL export is toggled via
the `make trace-up` / `make trace-down` targets (collector config override).

## Runtime v1 APIs
Run-centric APIs are exposed from API:
- `POST /v1/runs`
- `GET /v1/runs/{run_id}`
- `GET /v1/runs/{run_id}/timeline`
- `GET /v1/runs/{run_id}/stream` (SSE)
- `POST /v1/runs/{run_id}/approve`
- `POST /v1/runs/{run_id}/reject`

Contract reference: `docs/contracts/openapi-v1-runs.yaml`

## Production scaling
Kubernetes starter manifests and scaling guidance live in `docs/production-scaling.md`
and `infra/k8s/`.

## Audit forwarding
Optional forwarding is supported:
- Syslog: `AUDIT_FORWARD_SYSLOG=true`, `AUDIT_SYSLOG_HOST`, `AUDIT_SYSLOG_PORT`
- HTTP: `AUDIT_FORWARD_HTTP_URL`, `AUDIT_FORWARD_HTTP_HEADERS` (JSON), `AUDIT_FORWARD_HTTP_TIMEOUT`

## LLM audit events
Agent-runtime emits `llm.call` audit events into the API audit table via
`/v1/audit/ingest`. Configure:
- `AUDIT_INGEST_URL` (default `http://api:8000/v1/audit/ingest`)
- `AUDIT_INGEST_TOKEN` and matching `SERVICE_TOKEN` in API
- `LLM_LOG_SUMMARY=false` to keep summaries off (recommended)

## Smoke approvals
By default, `make smoke` runs a non-HITL workflow run. To include the approval
flow, set `SMOKE_APPROVALS=1`; the smoke script will run the workflow in the
`prod` environment so policy requires human approval. Example:
```sh
SMOKE_APPROVALS=1 make smoke
```
The smoke script creates a temporary workflow and deletes it (and its runs) at
the end to keep the UI clean. It also exercises agent runs:
- `POST /v1/agent/runs` (dev allow)
- `POST /v1/agent/runs` (prod approval or allow, depending on score)
- `POST /v1/agent/runs` (prod deny for destructive goal)

## Database migrations
The API container runs `alembic upgrade head` on startup (idempotent). You can
also run `make db-migrate` to apply Alembic migrations manually.

## Docs
- `docs/system-design.md`
- `docs/milestones.md`
- `docs/contracts/openapi.yaml`
- `docs/contracts/action-execution.md`
  - v1 action execution contract schemas and OpenAPI components reference.
- `docs/auth.md`
- `docs/policy.md`
- `docs/workflows.md`
- `docs/agent-runtime.md`
- `docs/vector-store.md`
- `docs/gitops.md`
- `docs/observability.md`
- `docs/production-scaling.md`
- `docs/production-handbook.md`
- `docs/operator-runbook.md`
- `docs/user-guide.md`

## Auth
The local stack includes Keycloak for OIDC. See `docs/auth.md` for setup and roles.

## Policy
OPA guardrails and policy evaluation are documented in `docs/policy.md`.

## Workflows
Workflow registry and plugin invocation details are documented in `docs/workflows.md`.
Workflow params can include secret references
(`secretkeyref:plugin:<name>:<path>`); they are resolved through the Plugin
Gateway before invoking external orchestrators.

MCP servers are supported via `plugin_type=mcp` with `tools/list` and `tools/call`
actions. See `docs/workflows.md` for registration and usage examples.
The local engine stack (Airflow + Jenkins + n8n) is documented in
`docs/workflows.md`.
Plugin/workflow registration script usage is also documented there.

## User chat
The UI includes a User Chat panel powered by the `user_chat` agent. Chat messages
are stored per user and can execute tool calls for workflows, plugins, audits,
approvals, and alerts via `/v1/chat`.

`/v1/chat`, `/v1/agent/plan`, and `/v1/agent/runs` are compatibility paths.
They launch v1 runs through `runtime-orchestrator` and return compatibility
envelopes.

## Repo Notes
- `AGENTS.md` defines workflow and non-negotiables.
- `skills/` contains Codex skills for Autonoma implementation.
