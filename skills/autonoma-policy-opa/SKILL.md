---
name: autonoma-policy-opa
description: Build policy guardrails with OPA (Rego) for Autonoma actions, including pre-execution checks, explainable decisions, and testable policy bundles.
---

# OPA Policy Guardrails (Policy-as-Code)

## What policies must cover
- RBAC augmentation: action allowed for role?
- Risk classification: low/medium/high → triggers HITL?
- Safety constraints:
  - No destructive ops in prod without approval
  - No public exposure of sensitive services
  - Cost guardrails (instance sizes, quotas)
- Plugin allow-lists:
  - Which agents can invoke which plugins/actions

## Integration points
- API gateway: policy check for user-triggered actions
- Orchestrator: policy check for plan steps before execution
- Plugin Gateway: policy check for every invocation

## Implementation requirements
- Policy inputs must include:
  - actor (user/agent), roles, tenant/workspace
  - action type, target resource metadata
  - environment (dev/stage/prod)
  - proposed parameters (redacted where needed)
- Policy outputs must include:
  - allow/deny
  - reasons (explainable)
  - required approvals (if any)

## Testing
- Use `opa test` for Rego unit tests.
- Add golden test cases for typical scenarios.

## Deliverables
- `apps/policy/bundle/` Rego policies
- Policy decision API (thin wrapper) OR embedded OPA sidecar integration
- Policy tests + CI step

## Review checklist
- Default deny everywhere
- Deterministic policy outcomes
- Human-readable decision reasons persisted to audit
