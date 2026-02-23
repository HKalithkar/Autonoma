from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, generate_latest

AUDIT_EVENTS = Counter(
    "autonoma_audit_events_total",
    "Audit events emitted",
    ["event_type", "outcome", "source"],
)

WORKFLOW_REGISTRY = Counter(
    "autonoma_workflow_registry_total",
    "Workflow registry actions",
    ["action"],
)

PLUGIN_REGISTRY = Counter(
    "autonoma_plugin_registry_total",
    "Plugin registry actions",
    ["action", "plugin_type"],
)

WORKFLOWS_TOTAL = Gauge(
    "autonoma_workflows_total",
    "Total workflows in registry",
    ["tenant_id"],
)

PLUGINS_TOTAL = Gauge(
    "autonoma_plugins_total",
    "Total plugins in registry",
    ["tenant_id"],
)

WORKFLOW_RUNS = Counter(
    "autonoma_workflow_runs_total",
    "Workflow runs by status",
    ["status", "environment"],
)

PLUGIN_INVOCATIONS = Counter(
    "autonoma_plugin_invocations_total",
    "Plugin invocations",
    ["plugin", "action", "status"],
)

APPROVALS = Counter(
    "autonoma_approvals_total",
    "Approval requests and decisions",
    ["status", "target_type"],
)

LLM_CALLS = Counter(
    "autonoma_llm_calls_total",
    "LLM calls by agent",
    ["agent_type", "status", "model"],
)

LLM_LATENCY_MS = Histogram(
    "autonoma_llm_latency_ms",
    "LLM call latency in milliseconds",
    ["agent_type", "status"],
)


def render_metrics() -> bytes:
    return generate_latest()
