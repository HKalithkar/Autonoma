# GitOps Integration (Slice 7)

## Overview
GitOps execution is implemented via the Plugin Gateway. Agents and workflows
never call Git providers directly. The gateway creates a change request and
returns a `job_id` plus a callback URL for pipeline status updates.

## Flow
1. Workflow run invokes plugin gateway action `gitops.create_change`.
2. Plugin gateway returns `job_id` and `callback_url`.
3. External Git provider or pipeline posts status to plugin gateway `/gitops/webhook`.
4. Plugin gateway forwards to API `/v1/gitops/webhook` with service token.
5. API updates workflow run `gitops` metadata and audit log.

## Configuration
Environment variables:
- `GITOPS_WEBHOOK_URL` (plugin gateway -> API callback URL)
- `GITOPS_WEBHOOK_TOKEN` (plugin gateway)
- `SERVICE_TOKEN` (API, must match `GITOPS_WEBHOOK_TOKEN`)

## Local test flow
1) Trigger the `gitops-change` workflow from UI.
2) Simulate a webhook:
```sh
curl -X POST http://localhost:8002/gitops/webhook \\
  -H "Content-Type: application/json" \\
  -d '{"workflow_run_id":"<run-id>","status":"success","commit_sha":"abc123","details":{"tenant_id":"default"}}'
```
3) Check `GET /v1/runs` for `gitops.status` updates and the Audit panel for `gitops.webhook`.

When a webhook reports `failed`/`error`, the API writes a failure record into
vector memory so future planning can reference similar incidents.

## Plugin action
- plugin: `gitops`
- action: `create_change`
- params (minimum):
  - `workflow_run_id`
  - `repo`, `branch`, `path`, `changes` (implementation-specific)

## Webhook payload
`POST /v1/gitops/webhook` with `x-service-token`:
```json
{
  "workflow_run_id": "uuid",
  "status": "queued|running|success|failed",
  "commit_sha": "sha",
  "pr_url": "https://...",
  "pipeline_id": "pipeline-123",
  "details": {}
}
```

## Security
- Service token required for webhook forwarding (`GITOPS_WEBHOOK_TOKEN` must match API `SERVICE_TOKEN`).
- Audit events are emitted on webhook receipt.
- No secrets are logged; payload is stored as metadata only.
