# Architecture Compliance Matrix

This matrix maps the Autonoma architecture specification to the current implementation
state in this repository.

Legend:
- Done: Implemented and exercised in the current codebase.
- Partial: Implemented in a minimal or dev-focused form; gaps remain.
- Missing: Not implemented yet.

## Component coverage

| Spec Section | Requirement | Status | Evidence | Notes / Gaps |
| --- | --- | --- | --- | --- |
| 3.1 Orchestrator Agent | Orchestrator agent coordinating tasks | Partial | `apps/agent_runtime/app/planner.py`, `apps/agent_runtime/app/main.py`, `apps/runtime_orchestrator/app/temporal_engine.py` | Orchestrator logic exists; Temporal integration is hook-only (no server/UI/worker rollout yet). |
| 3.2 Security Guardian Agent | Security/compliance agent | Partial | `apps/api/app/agent_eval.py`, `apps/api/app/policy.py` | Safety/evals + policy enforcement exist; dedicated guardian agent not split as its own service. |
| 3.3 Event Response Coordinator | Ingest + correlate events and orchestrate responses | Partial | `apps/api/app/routes/events.py`, `apps/api/app/routes/chat.py` | Event ingestion + trail present; no streaming event bus or correlation engine yet. |
| 3.4 Reasoning & Planning Engine | LLM-backed planning with tool usage | Partial | `apps/agent_runtime/app/planner.py`, `apps/agent_runtime/app/llm.py` | LLM planning + tool calls exist; no multi-model routing, and Temporal durable execution is not fully deployed. |
| 3.5 Plugin Gateway (MCP) | Secure tool invocation with policy checks | Done | `apps/plugin_gateway/app/main.py` | Enforces policy + audit; no retries/backoff or idempotency keys yet. |
| 3.6 Plugin Registry | Plugin catalog + metadata | Done | `apps/api/app/routes/plugins.py`, `apps/api/app/models.py` | Supports CRUD + plugin types + auth refs. |
| 3.7 GitOps Engine | GitOps integration + callbacks | Partial | `apps/api/app/routes/gitops.py`, `apps/plugin_gateway/app/main.py` | Webhook + job metadata flow exists; no real repo commits/ArgoCD pipeline yet. |
| 3.8 HITL Approval Framework | Approval workflow + UI | Done | `apps/api/app/routes/approvals.py`, `apps/web/src/App.tsx` | End-to-end approval gate for runs. |
| 3.9 Vector & Time-Series Memory Stores | Vector + time-series memory | Partial | `apps/agent_runtime/app/vector_store.py`, `apps/agent_runtime/app/memory.py` | Vector + Redis short-term memory exist; time-series DB missing. |
| 3.10 UI/API Layer | UI + API gateway | Done | `apps/web/src/App.tsx`, `apps/api/app/main.py` | UI covers workflows/plugins/approvals/audit/events. |
| 3.11 Observability Layer | Metrics, logs, traces | Partial | `infra/prometheus.yml`, `infra/grafana/*`, `apps/api/app/audit.py` | Metrics + audit logs done; full OTEL tracing not end-to-end. |
| 3.12 Governance (RBAC, Policy, Audit) | RBAC + OPA + audit | Done | `apps/api/app/rbac.py`, `apps/api/app/policy.py`, `libs/common/audit.py` | Default deny, audited decisions present. |
| 3.13 Agent Evaluation & Safety | Safety scoring + gating | Partial | `apps/api/app/agent_eval.py`, `apps/api/app/routes/agent.py` | Eval scoring exists; advanced safety gates and RL loops pending. |

## Platform integrations

| Spec Section | Requirement | Status | Evidence | Notes / Gaps |
| --- | --- | --- | --- | --- |
| 4.0 Plugin & Workflow Integration | External workflow engines via plugins | Partial | `apps/plugin_gateway/app/main.py`, `apps/api/app/routes/workflows.py` | Reference plugin stub only; real Argo/Airflow/Jenkins integration pending. |
| 5.0 Data & Control Flow | Event-driven + shared memory | Partial | `apps/api/app/routes/events.py`, `apps/agent_runtime/app/memory.py` | SSE + Redis/VDB present; Kafka/event bus missing. |
| 6.0 Security & Compliance | IAM, RBAC, policy, audit | Partial | `apps/api/app/auth.py`, `apps/api/app/rbac.py`, `apps/api/app/policy.py` | OIDC + policy + audit done; mTLS/workload identity not implemented. |
| 7.0 Scalability & Resilience | Horizontal scaling + HA | Partial | `infra/docker-compose.yml`, `docs/production-handbook.md` | Local compose only; K8s/HA/autoscaling manifests pending. |

## Summary of key gaps

- Service-to-service security: mTLS/workload identity not implemented.
- Event bus is implemented with NATS JetStream; Temporal is only partially implemented
  (client starter hook present, but server/UI/worker rollout pending).
- Time-series DB missing; only metrics + vector store are present.
- GitOps pipeline is stubbed via webhook; no actual repo commit/apply flow.
- Production scaling/HA manifests (K8s) not delivered yet.
