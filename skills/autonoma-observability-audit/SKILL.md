---
name: autonoma-observability-audit
description: Add full observability (metrics/logs/traces) + immutable-ish audit logging across all Autonoma components, with correlation IDs and redaction.
---

# Observability + Audit

## Observability must include
- OpenTelemetry traces across:
  - API → agents → policy → plugin gateway → gitops
- Metrics:
  - request counts/latency
  - workflow success/failure
  - plugin invocation outcomes
  - LLM calls (count/latency/errors) without leaking prompts
- Logs:
  - structured JSON logs
  - correlation_id, actor_id, tenant_id

## Audit logging
- Append-only audit events for:
  - user actions
  - agent decisions (plan + rationale summary)
  - policy allow/deny + reasons
  - plugin invocations (redacted params)
  - approvals
  - gitops commits + pipeline results

## Deliverables
- OTEL SDK instrumentation
- Grafana dashboards (starter)
- Central log pipeline config (local dev ok)
- Audit table + writer library + tests

## Review checklist
- Redaction verified
- Correlation IDs present everywhere
- No sensitive payloads in traces/logs
