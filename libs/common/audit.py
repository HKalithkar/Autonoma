"""Structured audit logging with redaction."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from libs.common.context import get_request_context
from libs.common.metrics import AUDIT_EVENTS

_LOGGER = logging.getLogger("autonoma.audit")

_SENSITIVE_KEYS = {"token", "access_token", "refresh_token", "authorization", "secret"}


def _describe_event(event_type: str, outcome: str, details: dict[str, Any]) -> str:
    if event_type == "authn":
        reason = details.get("reason")
        return f"Authentication {outcome}" + (f" ({reason})" if reason else "")
    if event_type == "authz":
        permission = details.get("permission")
        return (
            f"Authorization {outcome} for {permission}"
            if permission
            else f"Authorization {outcome}"
        )
    if event_type == "policy":
        action = details.get("action")
        return f"Policy decision {outcome} for {action}" if action else f"Policy decision {outcome}"
    if event_type == "workflow.register":
        workflow_id = details.get("workflow_id")
        return f"Workflow registered ({workflow_id})" if workflow_id else "Workflow registered"
    if event_type == "workflow.delete":
        workflow_id = details.get("workflow_id")
        return f"Workflow deleted ({workflow_id})" if workflow_id else "Workflow deleted"
    if event_type == "plugin.register":
        plugin_id = details.get("plugin_id")
        return f"Plugin registered ({plugin_id})" if plugin_id else "Plugin registered"
    if event_type == "plugin.invoke":
        plugin = details.get("plugin")
        action = details.get("action")
        suffix = f"{plugin}:{action}" if plugin and action else (plugin or action)
        return f"Plugin invoke {outcome}" + (f" ({suffix})" if suffix else "")
    if event_type == "approval.requested":
        target_type = details.get("target_type") or "workflow"
        return f"Approval requested for {target_type}"
    if event_type == "approval.decision":
        decision = details.get("decision")
        return f"Approval {decision}" if decision else "Approval decision recorded"
    if event_type == "agent.run.created":
        run_id = details.get("agent_run_id")
        return f"Agent run created ({run_id})" if run_id else "Agent run created"
    if event_type == "agent.eval.scored":
        score = details.get("score")
        return (
            f"Agent evaluation scored ({score})" if score is not None else "Agent evaluation scored"
        )
    if event_type == "agent.eval.denied":
        return "Agent evaluation denied"
    if event_type == "agent.plan.refused":
        reason = details.get("reason")
        return f"Agent plan refused ({reason})" if reason else "Agent plan refused"
    if event_type == "event.webhook":
        event_type_name = details.get("event_type")
        return (
            f"Event webhook received ({event_type_name})"
            if event_type_name
            else "Event webhook received"
        )
    if event_type == "secret.resolve":
        ref = details.get("ref")
        return f"Secret resolved ({ref})" if ref else "Secret resolved"
    if event_type == "healthcheck":
        component = details.get("component")
        return f"Healthcheck recorded ({component})" if component else "Healthcheck recorded"
    return f"Audit event {event_type}"


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if k in _SENSITIVE_KEYS else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def audit_event(
    event_type: str,
    outcome: str,
    details: dict[str, Any],
    *,
    source: str | None = None,
) -> None:
    context = get_request_context()
    resolved_source = source or os.getenv("SERVICE_NAME", "unknown")
    if "description" not in details:
        details = {**details, "description": _describe_event(event_type, outcome, details)}
    payload = {
        "event_type": event_type,
        "outcome": outcome,
        "source": resolved_source,
        "correlation_id": context.correlation_id,
        "actor_id": context.actor_id,
        "tenant_id": context.tenant_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": _redact(details),
    }
    AUDIT_EVENTS.labels(event_type=event_type, outcome=outcome, source=resolved_source).inc()
    _LOGGER.info(json.dumps(payload, sort_keys=True))
