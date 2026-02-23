# Policy Guardrails (Slice 2)

## Overview
Policy decisions are enforced via OPA. Every policy evaluation returns:
- `allow`: boolean
- `deny_reasons`: list of strings
- `required_approvals`: list of approvals required for execution

API calls include `correlation_id`, `actor_id`, and `tenant_id` in policy input.

## Policy Endpoint
`POST /v1/policy/check`

Example payload:
```json
{
  "action": "workflow:run",
  "resource": { "id": "workflow-123" },
  "parameters": { "env": "prod" }
}
```

## Local OPA
OPA runs at `http://policy:8181` in docker compose. Set `OPA_URL` in `.env` if needed.

## Current Rules
- Default deny.
- Allow `auth:me` and `policy:check`.
- `workflow:run` in `prod` (from run payload) requires a `human_approval`.
- `agent:run` is allowed for all environments in Slice 4.

## HITL Approvals
When a policy decision returns `required_approvals`, the API creates an approval
request and sets the workflow run status to `pending_approval`. The run only
resumes after an authorized approver records a decision.

Invalid approval IDs return `400 Invalid approval id` on decision requests.

## Safety gating
Agent safety evaluations can independently require approvals or deny a run even
when policy allows the action. Policy decisions remain authoritative and are
evaluated before safety scoring.
