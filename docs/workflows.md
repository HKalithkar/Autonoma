# Workflows & Plugins (Slice 3)

## Overview
Workflows are registered definitions that invoke external systems via the Plugin Gateway.
All workflow runs are authorized via RBAC and policy checks and are audited.
GitOps workflows use the plugin gateway and update run metadata via webhook callbacks.

## Plugin Registry
Endpoints:
- `GET /v1/plugins`
- `POST /v1/plugins`

Plugins include:
- `name`, `version`, `plugin_type`
- `endpoint` (plugin gateway URL)
- `actions` metadata
- `allowed_roles`
- `auth_type`, `auth_ref`, `auth_config`

`plugin_type` groups plugins by capability:
- `workflow` (orchestrators like Airflow/Argo/Flux)
- `secret` (secret managers)
- `mcp` (MCP servers)
- `api` (generic API endpoints)
- `other`

`auth_type` describes how the plugin authenticates (metadata only). Use
`auth_ref` to point at a secret reference (e.g. `secretkeyref:plugin:vault-resolver:token`)
and `auth_config` for non-secret metadata (e.g. username, header name).

List filtering:
- `GET /v1/plugins?plugin_type=secret`
- `GET /v1/plugins?name=vault-resolver`

### MCP server plugins
MCP server entries use `plugin_type=mcp` and point `endpoint` at the MCP JSON-RPC
HTTP endpoint (for example: `http://mcp-server:9000/mcp`).

Supported MCP actions:
- `tools/list`
- `tools/call` (expects `params` to include the tool name and arguments)

The Plugin Gateway resolves the MCP plugin metadata via
`GET /v1/plugins/internal/resolve` (service token required) and forwards the
JSON-RPC payload to the MCP server. Auth headers are derived from the plugin
`auth_type` and `auth_ref` (resolved via `secretkeyref:` when present).

Example MCP registration:
```json
{
  "name": "inventory-mcp",
  "version": "v1",
  "plugin_type": "mcp",
  "endpoint": "http://mcp-server:9000/mcp",
  "actions": { "tools/list": {}, "tools/call": {} },
  "auth_type": "bearer",
  "auth_ref": "secretkeyref:plugin:vault-resolver:kv/autonoma#mcp_token"
}
```

### Vault secret plugin (dev)
The dev stack seeds a `vault-resolver` plugin when `DB_SEED=true`. It uses
`auth_ref=env:VAULT_TOKEN` and `auth_config.provider=vault` so the Plugin Gateway
can read Vault secrets without storing credentials in the DB.

Manual registration example:
```json
{
  "name": "vault-resolver",
  "version": "v1",
  "plugin_type": "secret",
  "endpoint": "http://plugin-gateway:8002/invoke",
  "actions": { "resolve": { "description": "Resolve Vault secret" } },
  "auth_type": "bearer",
  "auth_ref": "env:VAULT_TOKEN",
  "auth_config": {
    "provider": "vault",
    "addr": "http://vault:8200",
    "mount": "kv"
  }
}
```

Example MCP workflow action:
```json
{
  "name": "mcp-tool-call",
  "plugin_id": "<mcp-plugin-id>",
  "action": "tools/call",
  "description": "Call an MCP tool"
}
```

Example MCP run payload (forwarded as JSON-RPC params):
```json
{
  "environment": "dev",
  "params": {
    "name": "search_assets",
    "arguments": {
      "query": "db instances created in last 24h"
    }
  }
}
```

## Workflow Registry
Endpoints:
- `GET /v1/workflows`
- `POST /v1/workflows`
- `DELETE /v1/workflows/{workflow_id}`

Workflow fields:
- `name`, `description`
- `plugin_id`
- `action`
- `input_schema` (optional JSON Schema used to validate run params)

Invalid `plugin_id` values return `400 Invalid plugin id`.

## Triggering Runs
Endpoint:
- `POST /v1/workflows/{workflow_id}/runs`

Run requests are:
1) RBAC checked (`workflow:run`)
2) Policy evaluated via OPA
3) If approvals are required, the run is marked `pending_approval` and an approval
   request is created.
4) Otherwise, forwarded to Plugin Gateway for invocation.

Invalid `workflow_id` values return `400 Invalid workflow id`.

Run payloads must include `environment`:
```json
{
  "environment": "dev",
  "params": {
    "dag_id": "health-check"
  }
}
```

### Input schema validation
If a workflow has an `input_schema`, run params are validated against it on every run.
Example schema for a reboot workflow (server name required, optional metadata):
```json
{
  "type": "object",
  "required": ["server_name"],
  "properties": {
    "server_name": { "type": "string" },
    "scheduled_time": { "type": "string" },
    "servicenow_ticket": { "type": "string" },
    "reason": { "type": "string" }
  }
}
```

## Execution Engines (Airflow + Jenkins + n8n)
Autonoma forwards workflow runs to external engines through the Plugin Gateway. The
runtime orchestrator handles workflow execution and delegates side effects via
Plugin Gateway.

### Step-by-step setup
1) Start the core stack:
```sh
make up
```

2) Start the execution engines (choose one or both):
```sh
make engines-airflow-up
```
```sh
make engines-jenkins-up
```
```sh
make engines-up
```
Vault dev (OSS) is started with the engines stack and is used for `vault-resolver`.

For n8n local startup, bootstrap now does two things automatically:
- imports the 4 Autonoma dummy workflows and forces them to `active=true` before runtime starts
- creates the initial owner account from `N8N_PRESET_OWNER_*` env vars (first startup only)

3) Seed or register plugins/workflows:
- New databases: ensure `DB_SEED=true` so the Airflow/Jenkins/n8n plugins and dummy
  workflows are created automatically.
- Existing databases: register the plugins/workflows manually (examples below).

### Registration script
You can register plugins and workflows with the helper script:
```sh
scripts/register_plugins_workflows.sh scripts/inputs/airflow.json scripts/inputs/jenkins.json scripts/inputs/n8n.json
```

The script prompts for Keycloak username/password and exchanges them for a bearer token.
Override defaults with:
```sh
API_BASE=http://localhost:8000 \\
KEYCLOAK_URL=http://localhost:8080 \\
KEYCLOAK_REALM=autonoma \\
OIDC_CLIENT_ID=autonoma-api \\
OIDC_CLIENT_SECRET=autonoma-api-secret \\
scripts/register_plugins_workflows.sh scripts/inputs/airflow.json
```

### Plugin registration (manual)
Register the Airflow plugin:
```sh
curl -X POST http://localhost:8000/v1/plugins \\
  -H "authorization: Bearer $TOKEN" \\
  -H "content-type: application/json" \\
  -d '{
    "name": "airflow",
    "plugin_type": "workflow",
    "endpoint": "http://plugin-gateway:8002/invoke",
    "actions": { "trigger_dag": { "description": "Trigger an Airflow DAG" } },
    "allowed_roles": { "run": ["operator", "admin"] },
    "auth_type": "none",
    "auth_config": {}
  }'
```

Register the Jenkins plugin:
```sh
curl -X POST http://localhost:8000/v1/plugins \\
  -H "authorization: Bearer $TOKEN" \\
  -H "content-type: application/json" \\
  -d '{
    "name": "jenkins",
    "plugin_type": "workflow",
    "endpoint": "http://plugin-gateway:8002/invoke",
    "actions": { "trigger_job": { "description": "Trigger a Jenkins job" } },
    "allowed_roles": { "run": ["operator", "admin"] },
    "auth_type": "none",
    "auth_config": {}
  }'
```

### Workflow registration (manual)
Example Airflow workflow:
```sh
curl -X POST http://localhost:8000/v1/workflows \\
  -H "authorization: Bearer $TOKEN" \\
  -H "content-type: application/json" \\
  -d '{
    "name": "airflow-daily-health",
    "description": "Trigger daily health DAG",
    "plugin_id": "<airflow-plugin-id>",
    "action": "trigger_dag:dummy_daily_health"
  }'
```

Example Jenkins workflow:
```sh
curl -X POST http://localhost:8000/v1/workflows \\
  -H "authorization: Bearer $TOKEN" \\
  -H "content-type: application/json" \\
  -d '{
    "name": "jenkins-dummy-build",
    "description": "Trigger dummy build job",
    "plugin_id": "<jenkins-plugin-id>",
    "action": "trigger_job:dummy-build"
  }'
```

### Running the dummy workflows
- Airflow dummy DAGs: `dummy_daily_health`, `dummy_cache_refresh`, `dummy_cost_report`,
  `dummy_index_rebuild`
- Jenkins dummy jobs: `dummy-build`, `dummy-test`, `dummy-deploy`, `dummy-backup`
- n8n dummy webhook workflows: `autonoma-health-check`, `autonoma-cache-refresh`,
  `autonoma-cost-report`, `autonoma-index-rebuild`

When invoking a workflow run, you can override the target in params:
```json
{
  "environment": "dev",
  "params": {
    "dag_id": "dummy_daily_health"
  }
}
```

### Approvals
Endpoints:
- `GET /v1/approvals`
- `POST /v1/approvals/{approval_id}/decision`

Approval decisions update the workflow run status and resume execution when approved.

### Runs feed
Endpoint:
- `GET /v1/runs`

Returns recent runs with status, job_id, approval status, and `gitops` metadata.

For async engine adapters, run status can be updated by service callbacks through:
- `POST /v1/runs/internal/status` (service token required)

Example `gitops` payload:
```json
{
  "status": "success",
  "commit_sha": "abc123",
  "pr_url": "https://git.example/pr/42",
  "pipeline_id": "pipeline-42"
}
```

## GitOps workflows
GitOps runs use the plugin gateway action `gitops.create_change`. The gateway returns
a `job_id` and callback URL for pipeline status updates. The API exposes:
- `POST /v1/gitops/webhook` (service token required)

Webhook payloads update the `gitops` field on workflow runs.

## Event response webhook
The API exposes `POST /v1/events/webhook` (service token required) to accept
monitoring/alert payloads and trigger the Event Response Coordinator. The payload
is converted into an agent plan and persisted as an agent run (with approvals
if required).

Event ingestion history is available via `GET /v1/events` (requires `audit:read`).
Each record includes the policy decision, agent evaluation, and a trail of
actions taken by the event response flow.

## Secret references in workflow params
Workflow params can include secret references in the form
`secretkeyref:plugin:<name>:<path>`. The API resolves these by looking up
`plugin_type=secret` in the registry and calling the Plugin Gateway `resolve`
action before invoking the external orchestrator. Resolved secret values are
never stored or logged; the invocation audit retains only the reference or a
redacted placeholder.

Example:
```json
{
  "params": {
    "api_key": "secretkeyref:plugin:vault-resolver:kv/autonoma#airflow",
    "dag_id": "health"
  },
  "environment": "dev"
}
```

## Seed Data
On startup (when `DB_SEED=true`), reference plugins and workflows are created:
- Plugin: `airflow`
- Workflows: `airflow-daily-health`, `airflow-cache-refresh`, `airflow-cost-report`,
  `airflow-index-rebuild`
- Plugin: `jenkins`
- Workflows: `jenkins-dummy-build`, `jenkins-dummy-test`, `jenkins-dummy-deploy`,
  `jenkins-dummy-backup`
- Plugin: `gitops`
- Workflow: `gitops-change`

## Migrations
Use Alembic for schema upgrades:
```sh
make db-migrate
```

## Auto-create (dev only)
When `DB_AUTO_CREATE=true`, the API will create tables on startup for local dev.
