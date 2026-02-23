# Action Execution Contract (v1)

This document describes the v1 Action Execution contract used across the API,
Agent Runtime, Plugin Gateway, Policy Engine, Approvals, and Audit systems.

## Location
- JSON Schemas: `contracts/action/v1/`
- OpenAPI components: `contracts/openapi/action_execution_components.yaml`

## Schemas (v1)
All schemas are strict (`additionalProperties: false`) and require:
- `correlation_id` (uuid)
- `created_at` (date-time)
- `actor` (entity initiating/emitting the object)

Execution-related schemas also require `idempotency_key`:
- `ActionRequest`
- `ActionExecutionResult`
- `AuditEvent` when `event_category = execution`

### ActionRequest
Canonical request to execute an action via a tool/plugin.

### ActionPlan
Ordered set of steps; each step contains an ActionRequest-like `action` object.

### PolicyDecision
Policy evaluation result for a requested action.

### ApprovalRequest
Request for human approval prior to execution.

### ApprovalDecision
Outcome of an approval decision.

### ActionExecutionResult
Result of executing an action, including outputs, error (if any), and timing.

### AuditEvent
Audit event emitted for action lifecycle and related activities.
- `event_category` is required and drives idempotency requirements for execution events.

## Usage notes
- Schemas are versioned under `v1` to allow future evolution without breaking clients.
- OpenAPI 3.1 components reference the JSON Schemas directly for reuse in APIs.
