# Observability Stack (Prometheus + Grafana)

## Overview
Local observability is provided by:
- OpenTelemetry Collector (OTLP receiver + Prometheus exporter)
- Prometheus (scrapes OTEL metrics)
- Grafana (pre-provisioned datasource + starter dashboard)
- Langfuse (OTEL trace viewer, optional stack)

## Services
- OTEL Collector: `http://localhost:4318` (OTLP HTTP)
- Prometheus: `http://localhost:${PROMETHEUS_PORT:-9090}`
- Grafana: `http://localhost:${GRAFANA_PORT:-3001}`
- Langfuse: `http://localhost:${LANGFUSE_PORT:-3002}` (when `make trace-up` is running)

## Startup
```sh
make up
make trace-up
```

## Langfuse tracing
Langfuse ingests OTEL traces from the collector. Start the tracing stack with
`make trace-up`.
To enable/disable exports, `make trace-up` swaps the collector config to
`/etc/otel-collector-langfuse.yaml` and `make trace-down` restores the base
config.

Configure the OTEL exporter authorization header via `LANGFUSE_OTLP_AUTH_HEADER`
and point the collector to `LANGFUSE_OTLP_ENDPOINT`. See `.env.example` for defaults.
Set `LANGFUSE_OTLP_AUTH_HEADER` to `Basic <base64(public_key:secret_key)>` and
use the base endpoint (`/api/public/otel`); the exporter appends `/v1/traces`.
We recommend storing Langfuse keys in Vault and resolving them into the OTEL
collector environment (e.g., via your secrets manager) instead of committing
raw keys into `.env`.
For local dev, the Vault init script seeds `kv/langfuse` with the public/secret
keys from `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` when you run
`make engines-up`.

## Grafana access
- URL: `http://localhost:${GRAFANA_PORT:-3001}`
- User: `${GRAFANA_ADMIN_USER:-admin}`
- Password: `${GRAFANA_ADMIN_PASSWORD:-admin}`

The "Autonoma Overview" dashboard is provisioned under the "Autonoma" folder.
Grafana is configured to allow embedding in the UI in local dev
(`GF_SECURITY_ALLOW_EMBEDDING=true`, anonymous viewer enabled).

## Prometheus scrape
Prometheus scrapes:
- OTEL collector metrics at `otel-collector:8889`.
- API metrics at `/metrics`
- Agent runtime metrics at `/metrics`
- Runtime orchestrator metrics at `/metrics`
- Plugin gateway metrics at `/metrics`

Metrics cover:
- LLM calls by agent (`autonoma_llm_calls_total`)
- Workflow runs by status (`autonoma_workflow_runs_total`)
- Runtime v1 runs by status (`autonoma_runtime_runs_total`)
- Runtime policy gate outcomes (`autonoma_runtime_policy_decisions_total`)
- Runtime tool retries/failures (`autonoma_runtime_tool_attempts_total`)
- Plugin invocations (`autonoma_plugin_invocations_total`)
- Approval requests/decisions (`autonoma_approvals_total`)
- Registry totals (`autonoma_workflows_total`, `autonoma_plugins_total`)

## Event stream (SSE)
The API exposes a server-sent events stream for real-time operational updates:
- Endpoint: `GET /v1/events/stream`
- Query params:
  - `since`: optional ISO timestamp to replay from
  - `once`: when `true`, emits current events once and closes the stream

The UI Events tab uses this stream to render live alerts and agent trails.
Event payloads are redacted (no prompt content or secrets).

For run-centric transparency, API also exposes:
- `GET /v1/runs/{run_id}/timeline` (replay/backfill)
- `GET /v1/runs/{run_id}/stream` (live SSE with resume via `Last-Event-ID` or `last_event_id`)

v1 runtime timelines are sourced from append-only run event storage, with
deterministic ordering and cursor semantics.

## Security notes
- Grafana is configured for local development only (no sign-ups).
- Do not expose Grafana or Prometheus publicly without auth and TLS.
