from __future__ import annotations

import os
import uuid
from typing import Any

from libs.common.audit import audit_event as log_audit_event
from libs.common.context import get_request_context

from .audit_forwarder import forward_audit_event
from .db import session_scope
from .models import AuditEvent, EventIngest

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
    if event_type == "agent.plan.created":
        plan_id = details.get("plan_id")
        return f"Agent plan created ({plan_id})" if plan_id else "Agent plan created"
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


def _source() -> str:
    return os.getenv("SERVICE_NAME", "api")


def audit_event(
    event_type: str,
    outcome: str,
    details: dict[str, Any],
    *,
    session=None,
    source: str | None = None,
) -> None:
    resolved_source = source or _source()
    if "description" not in details:
        details = {**details, "description": _describe_event(event_type, outcome, details)}
    log_audit_event(event_type, outcome, details, source=resolved_source)
    context = get_request_context()
    payload = {
        "event_type": event_type,
        "outcome": outcome,
        "source": resolved_source,
        "correlation_id": context.correlation_id,
        "actor_id": context.actor_id,
        "tenant_id": context.tenant_id,
        "details": _redact(details),
    }
    forward_audit_event(payload)
    # Mirror audit events into the event ingestion feed so UI "Events" is populated.
    event_payload: EventIngest | None = None
    if not event_type.startswith("event."):
        severity = "high" if outcome == "deny" else "info"
        status = outcome if outcome in {"allow", "deny"} else "completed"
        summary = details.get("description") or _describe_event(event_type, outcome, details)
        environment = os.getenv("ENVIRONMENT", "dev")
        approval_id = details.get("approval_id")
        agent_run_id = details.get("agent_run_id")
        if isinstance(approval_id, str):
            try:
                approval_id = uuid.UUID(approval_id)
            except ValueError:
                approval_id = None
        if isinstance(agent_run_id, str):
            try:
                agent_run_id = uuid.UUID(agent_run_id)
            except ValueError:
                agent_run_id = None
        event_payload = EventIngest(
            event_type=event_type,
            severity=severity,
            summary=summary,
            source=resolved_source,
            details=_redact(details),
            environment=environment,
            status=status,
            agent_run_id=agent_run_id,
            approval_id=approval_id,
            actions={"audit": {"event_type": event_type, "outcome": outcome}},
            correlation_id=context.correlation_id,
            tenant_id=context.tenant_id,
        )
    if session is None:
        with session_scope() as session_ctx:
            event = AuditEvent(
                event_type=event_type,
                outcome=outcome,
                source=resolved_source,
                details=_redact(details),
                correlation_id=context.correlation_id,
                actor_id=context.actor_id,
                tenant_id=context.tenant_id,
            )
            session_ctx.add(event)
            if event_payload is not None:
                session_ctx.add(event_payload)
    else:
        event = AuditEvent(
            event_type=event_type,
            outcome=outcome,
            source=resolved_source,
            details=_redact(details),
            correlation_id=context.correlation_id,
            actor_id=context.actor_id,
            tenant_id=context.tenant_id,
        )
        session.add(event)
        if event_payload is not None:
            session.add(event_payload)
