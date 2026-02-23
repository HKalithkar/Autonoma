# Autonoma Milestones (Slices)

This document tracks the planned delivery slices for Autonoma. Each slice lists
scope, exit criteria, and the primary commands to verify progress.

## Slice 0 — Repo Bootstrap & Dev Environment
**Scope**
- Monorepo layout + baseline tooling (lint/test/format).
- Docker compose dev environment.
- CI skeleton + security docs.

**Exit criteria**
- `make up` starts the stack.
- `make lint` and `make test` run in containers.
- README and security docs updated.

## Slice 1 — Auth + RBAC
**Scope**
- OIDC login via Keycloak.
- JWT validation and RBAC enforcement.
- Auth endpoints + audit of authz decisions.

**Exit criteria**
- Login flow works and `auth:me` returns identity.
- RBAC denies unauthorized endpoints.
- Auth allow/deny audited with correlation IDs.

## Slice 2 — Policy Guardrails (OPA)
**Scope**
- Policy decision API.
- Allow/deny reasons and required approvals in responses.
- Policy tests in CI.

**Exit criteria**
- `make policy-test` passes.
- Policy allow/deny audited.

## Slice 3 — Registry + Run Trigger
**Scope**
- Plugin registry API.
- Workflow registry API.
- Workflow run trigger via Plugin Gateway.
- Basic UI to list/register and run workflows.

**Exit criteria**
- Workflows can be registered and run from UI.
- Plugin invocation audited.

## Slice 4 — Observability + Run History UI
**Scope**
- Run status tracking + listing endpoints.
- Audit trail UI in web.
- OTEL trace/metrics integration surfaced.

**Exit criteria**
- Run history visible in UI.
- Audit events viewable end-to-end.

## Slice 5 — HITL Approvals
**Scope**
- Approval object model + API.
- UI approvals inbox.
- Pause/resume for policy-required actions.

**Exit criteria**
- Policy can require approvals.
- Approvals recorded and audited.

## Slice 6 — Agent Runtime + Memory
**Scope**
- Orchestrator + agent runtime.
- Short/long-term memory stores.
- Safe tool calling through Plugin Gateway.

**Exit criteria**
- Agent runs produce auditable plans and tool calls.

## Slice 7 — Plugin Gateway Hardening
**Scope**
- Schema validation, retries, idempotency.
- Contract tests for plugins.

**Exit criteria**
- Invalid payloads rejected.
- Retries and idempotency documented/tested.

## Slice 8 — Agent Evaluations + Safety Gating
**Scope**
- Eval scoring and gating.
- Regression tests for safety cases.

**Exit criteria**
- Low scores block or trigger HITL.
- Eval results logged and auditable.

## Slice 9 — GitOps Integration
**Scope**
- PR/commit flow for infra changes.
- Pipeline status tracking.

**Exit criteria**
- GitOps runs linked to workflow runs and audit.

## Slice 10 — CI Security & Release Hardening
**Scope**
- SAST, dependency scans, container scans.
- Integration smoke tests in CI.

**Exit criteria**
- CI gates pass for lint/test/policy/security.
