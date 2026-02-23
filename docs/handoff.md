# Codex Handoff

## Context
Chat UX improvements + cross-agent delegation implemented. Chat now supports detailed approval/run lookups (`approval.get`, `run.get`) and renders human-readable tool results. Chat can delegate to orchestrator planning via `agent.plan`. GitOps integration remains via Plugin Gateway with webhook callbacks. Observability dashboards and production scaling templates are now documented and scaffolded.

## Current status
- Tests: `make test` passes (Python + web).
- `make smoke` validates:
  - workflow run
  - agent run dev allow
  - agent run prod approval/allow
  - agent run prod destructive deny
- `make smoke` fails if stack is not up.

## Next steps
1) Start stack: `make up`
2) Run migrations: `make db-migrate`
3) Run smoke: `make smoke`

## If Alembic error appears
Verify `apps/api/alembic.ini` contains:
```
script_location = %(here)s/alembic
```

## Key files changed (Slice 5)
- Safety eval engine: `apps/api/app/agent_eval.py`
- Models + migration:
  - `apps/api/app/models.py`
  - `apps/api/alembic/versions/0007_agent_evaluations_and_approval_targets.py`
- Agent runs + approvals:
  - `apps/api/app/routes/agent.py`
  - `apps/api/app/routes/approvals.py`
  - `apps/api/app/routes/workflows.py`
- UI updates:
  - `apps/web/src/App.tsx`
  - `apps/web/src/App.test.tsx`
  - `apps/web/src/styles.css`
- Docs:
  - `docs/agent-runtime.md`
  - `docs/policy.md`
  - `docs/milestones.md`
  - `docs/auth.md`
  - `docs/contracts/openapi.yaml`
  - `README.md`
- Smoke: `scripts/smoke.sh`

## Key files changed (Chat delegation + detail lookups)
- Chat tools: `apps/api/app/chat_tools.py`
- Chat router: `apps/api/app/routes/chat.py`
- Chat prompt: `apps/agent_runtime/prompts/chat.txt`
- Web chat rendering: `apps/web/src/App.tsx`
- Tests:
  - `apps/api/tests/test_chat.py`
  - `apps/web/src/App.test.tsx`

## Key files changed (Observability + scaling)
- OTEL config: `infra/otel-collector.yaml`
- Prometheus/Grafana configs:
  - `infra/prometheus.yml`
  - `infra/grafana/provisioning/datasources/datasource.yml`
  - `infra/grafana/provisioning/dashboards/dashboard.yml`
  - `infra/grafana/dashboards/autonoma-overview.json`
- Docker compose: `infra/docker-compose.yml`
- Docs:
  - `docs/observability.md`
  - `docs/production-scaling.md`
  - `docs/milestones.md`
  - `docs/system-design.md`
  - `README.md`
- K8s templates: `infra/k8s/`

## TODO
- Consider adding `run.get`/`approval.get` to OpenAPI as internal tool actions documentation.
- Add IAM user create/disable endpoints.
- Add server-driven menu configuration for per-role navigation.
- Consider adding `run.get`/`approval.get` to OpenAPI as internal tool actions documentation.
