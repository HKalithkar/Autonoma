---
name: autonoma-mcp-plugin-gateway
description: Build the MCP Plugin Gateway + Plugin Registry, including secure plugin invocation, auth/secret handling, schema validation, retries, and auditing.
---

# MCP Plugin Gateway + Plugin Registry

## Components
1. Plugin Registry (catalog)
- CRUD plugins
- Store: name, version, capabilities/actions, endpoint, auth reference, allowed roles/agents

2. Plugin Gateway (invocation)
- Standard invoke API: `invoke(plugin, action, params, context)`
- Normalized responses: `status`, `result`, `error`, `task_id`
- Async jobs supported: polling + webhooks optional

## Security requirements
- Authenticate caller (user/agent) and pass identity into policy check.
- Authorize with OPA + RBAC.
- Secrets:
  - stored in vault/secret manager later
  - for prototyping: env-injected + encrypted-at-rest in dev only
- Output redaction: never log secrets/credentials.

## Reliability requirements
- Timeouts + retries
- Idempotency keys for external actions
- Correlation IDs propagated end-to-end

## Deliverables
- Registry DB tables + API
- Gateway service + plugin interface abstraction
- One reference plugin:
  - Airflow DAG trigger OR Argo workflow trigger OR Jenkins job trigger
- Tests:
  - contract tests for plugin schema
  - deny tests for unauthorized invocations
