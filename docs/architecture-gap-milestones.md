# Architecture Gap Milestones (Partial/Missing)

This document expands the **Partial/Missing** items from `docs/architecture-compliance.md`
into concrete milestones/slices with tasks, tests, and review criteria. These are designed
to follow the required Plan -> Implement -> Verify -> Review workflow.

## Scope
- Orchestrator and event coordination maturity
- Security guardian service boundaries
- Event bus / streaming backbone
- Time-series memory store
- GitOps real integration
- Observability end-to-end tracing
- Service-to-service identity and mTLS
- Production scaling/HA (K8s)
- Plugin gateway resilience (idempotency, retries)

---

## Slice G1: Orchestrator + Event Bus Backbone

Plan (goal):
- Introduce a real event backbone (Kafka/NATS) and wire orchestration stages to it.

Impacted modules/services:
- `apps/agent_runtime`, `apps/api`, `infra/`, `docs/contracts/events/*`

Concrete tasks:
- Add event bus service to `infra/docker-compose.yml` (NATS or Kafka).
- Define event schemas for run lifecycle, approvals, policy decisions, plugin invocations.
- Publish orchestration events from API/agent runtime instead of DB polling.
- Add consumer in Agent Runtime to progress plans based on events.
- Add correlation_id/actor_id/tenant_id to every event.

Tests:
- Integration tests for publish/consume (event flow).
- Contract tests for event schemas.
- Negative tests for missing correlation_id and rejected events.

Security checks:
- Ensure events are authenticated (service identity) and authorized (OPA).
- Redact sensitive fields in event payloads.

Review:
- Reliability: replay safety, idempotency on consumer.
- Observability: event counts, lag metrics.

Acceptance:
- Event-driven run progression without DB polling.
- Event schemas validated in CI.

---

## Slice G2: Security Guardian Service Boundary

Plan (goal):
- Split policy/safety enforcement into a dedicated Security Guardian service.

Impacted modules/services:
- `apps/api`, `apps/agent_runtime`, `policies/`, `infra/`

Concrete tasks:
- Create `apps/security_guardian` service with OpenAPI.
- Move agent safety checks and policy evaluation behind this service.
- Require all agent/tool decisions to call guardian before execution.
- Add audit events for guardian allow/deny with reasons.

Tests:
- Guardian API unit tests (allow/deny).
- Integration tests for API -> guardian -> OPA.
- Negative tests for unauthenticated calls.

Security checks:
- Default deny in guardian if policy unavailable.
- Enforce service identity and OPA authorization for calls.

Review:
- Least privilege on guardian API.
- Clear audit trail for every decision.

Acceptance:
- No tool execution without guardian allow.
- Guardian decisions fully audited.

---

## Slice G3: Event Response Coordinator (ERC)

Plan (goal):
- Implement a coordinator that correlates incoming events and schedules actions.

Impacted modules/services:
- `apps/api`, `apps/agent_runtime`, `apps/web`, `infra/`

Concrete tasks:
- Build ERC service (or module) with correlation state machine.
- Persist event trails with action history and outcomes.
- Add UI panel for event correlation and actions taken.
- Stream updates via SSE/WebSocket.

Tests:
- Unit tests for correlation logic.
- Integration tests for event ingestion -> action -> audit.

Security checks:
- Enforce access control on event history.
- Redact sensitive data in action details.

Review:
- Ensure idempotent action scheduling.
- Verify audit completeness.

Acceptance:
- Event trails show each action and outcome.
- ERC triggers follow-up actions reliably.

---

## Slice G4: Time-Series Memory Store

Plan (goal):
- Add a time-series database for operational memory and agent telemetry.

Impacted modules/services:
- `apps/agent_runtime`, `apps/api`, `infra/`

Concrete tasks:
- Add time-series DB service (Timescale/Influx) to compose.
- Implement storage adapter in agent runtime.
- Add query API for time-range memory.
- Add UI search/browse for time-series memory.

Tests:
- Adapter unit tests (write/read).
- API tests for time-range queries.

Security checks:
- Tenant scoping for reads/writes.
- Redaction of sensitive fields.

Review:
- Retention policies and storage limits.
- Query performance.

Acceptance:
- Time-series memory visible in UI.
- Query API returns correct ranges.

---

## Slice G5: GitOps Engine (Real Integration)

Plan (goal):
- Convert GitOps from webhook-only to real repo commit/apply flow.

Impacted modules/services:
- `apps/api`, `apps/plugin_gateway`, `infra/`, `docs/`

Concrete tasks:
- Implement plugin type `gitops` for repo commit + PR creation.
- Add webhook handler for pipeline status callbacks (ArgoCD/Flux).
- Store commit SHA and deployment status on workflow run.
- Add UI view for GitOps change history.

Tests:
- Contract tests for GitOps webhook payloads.
- Integration test for plugin invocation -> run update.

Security checks:
- Secret references resolved via plugin gateway.
- Audit events for each GitOps action.

Review:
- Idempotent retries on webhook timeouts.
- Clear failure reasons in UI.

Acceptance:
- GitOps run updates status from callback.
- GitOps history visible in UI.

---

## Slice G6: End-to-End OpenTelemetry Tracing

Plan (goal):
- Wire OTEL traces across API, agent runtime, plugin gateway, and UI.

Impacted modules/services:
- `apps/api`, `apps/agent_runtime`, `apps/plugin_gateway`, `infra/`

Concrete tasks:
- Add OTEL instrumentation for FastAPI + HTTP clients.
- Propagate trace context with correlation_id.
- Add Grafana dashboards for traces and per-service spans.

Tests:
- Trace propagation integration test (api -> plugin gateway).

Security checks:
- Redact PII and secrets in trace attributes.

Review:
- Trace sampling strategy.
- Dashboard usability.

Acceptance:
- Trace from UI request to plugin invocation visible.

---

## Slice G7: Service-to-Service Identity + mTLS

Plan (goal):
- Implement service identity and optional mTLS for internal calls.

Impacted modules/services:
- `apps/api`, `apps/agent_runtime`, `apps/plugin_gateway`, `infra/`

Concrete tasks:
- Add service tokens with rotation hooks.
- Add mTLS support in compose (dev CA).
- Enforce service auth on internal endpoints.

Tests:
- Unauthorized internal call tests.
- mTLS handshake test in CI.

Security checks:
- Default deny for untrusted identities.
- Audit failed authn/authz attempts.

Review:
- Ensure no hardcoded secrets.
- Clear docs for production certs.

Acceptance:
- Internal calls rejected without identity.
- mTLS works in dev compose.

---

## Slice G8: Production Scaling + HA (Kubernetes)

Plan (goal):
- Deliver K8s manifests with HA, autoscaling, and storage.

Impacted modules/services:
- `infra/`, `docs/production-handbook.md`

Concrete tasks:
- Add K8s manifests (Deployments, Services, HPA, Ingress).
- Add persistent volumes for Postgres, vector DB, time-series DB.
- Add runbooks for scaling and disaster recovery.

Tests:
- K8s manifest validation (kubeval/kustomize build).
- Smoke tests in KIND (optional in CI).

Security checks:
- Network policies for service isolation.
- Secrets via external secret store integration.

Review:
- Resource limits and autoscaling thresholds.
- Backup/restore tested.

Acceptance:
- K8s manifests deploy cleanly in local KIND.
- Production handbook updated with HA steps.

---

## Slice G9: Plugin Gateway Resilience & Idempotency

Plan (goal):
- Add retry/backoff and idempotency keys for plugin invocations.

Impacted modules/services:
- `apps/plugin_gateway`, `apps/api`

Concrete tasks:
- Add idempotency key field in invocation request/DB.
- Implement retry policy with exponential backoff.
- Add UI visibility for retries and final outcome.

Tests:
- Idempotency test for duplicate requests.
- Retry test for transient failures.

Security checks:
- Ensure idempotency keys are tenant-scoped.

Review:
- Avoid replaying side effects.
- Clear audit trail on retries.

Acceptance:
- Duplicate invocations do not double-execute.
- Retry attempts audited.

---

## Exit Criteria (Global)

- All slices have passing unit + integration tests.
- OPA policy checks enforced and audited.
- Correlation IDs present across services and events.
- Docs updated (user guide + production handbook + runbooks).
