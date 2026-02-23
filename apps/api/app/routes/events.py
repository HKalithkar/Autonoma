from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from libs.common.context import set_request_context

from ..agent_eval import evaluate_agent_run
from ..audit import audit_event
from ..db import session_scope
from ..models import AgentEvaluation, AgentRun, Approval, EventIngest, RuntimeEvent, RuntimeRun
from ..policy import evaluate_policy
from ..rbac import require_permission

router = APIRouter(prefix="/v1/events", tags=["events"])


class EventWebhook(BaseModel):
    event_type: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    source: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)
    environment: str = Field(default="prod", pattern="^(dev|stage|prod)$")
    correlation_id: str | None = None
    tenant_id: str = "default"


def _require_service_token(request: Request) -> None:
    token = request.headers.get("x-service-token")
    expected = os.getenv("SERVICE_TOKEN")
    if not token or not expected or token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def _agent_runtime_url() -> str:
    return os.getenv("AGENT_RUNTIME_URL", "http://agent-runtime:8001")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/webhook")
def ingest_event(payload: EventWebhook, request: Request) -> dict[str, Any]:
    _require_service_token(request)
    correlation_id = payload.correlation_id or str(uuid.uuid4())
    actor_id = "service:event-webhook"
    set_request_context(
        correlation_id=correlation_id,
        actor_id=actor_id,
        tenant_id=payload.tenant_id,
    )

    goal = f"Respond to alert: {payload.summary}"
    documents = [
        f"event_type: {payload.event_type}",
        f"severity: {payload.severity}",
        f"source: {payload.source}",
        f"details: {payload.details}",
    ]

    decision = evaluate_policy(
        action="event:respond",
        resource={"event_type": payload.event_type},
        parameters={"environment": payload.environment, "severity": payload.severity},
    )
    trail: list[dict[str, Any]] = [
        {
            "step": "event_received",
            "actor": actor_id,
            "status": "received",
            "timestamp": _utcnow().isoformat(),
        },
        {
            "step": "policy_check",
            "actor": "policy",
            "status": "allow" if decision.allow else "deny",
            "details": {
                "deny_reasons": decision.deny_reasons,
                "required_approvals": decision.required_approvals,
            },
            "timestamp": _utcnow().isoformat(),
        },
    ]
    if not decision.allow and not decision.required_approvals:
        audit_event(
            "event.webhook",
            "deny",
            {"event_type": payload.event_type, "severity": payload.severity},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"deny_reasons": decision.deny_reasons},
        )

    agent_payload = {
        "goal": goal,
        "environment": payload.environment,
        "tools": ["plugin_gateway.invoke"],
        "documents": documents,
        "execute_tools": False,
        "context": {
            "correlation_id": correlation_id,
            "actor_id": actor_id,
            "tenant_id": payload.tenant_id,
        },
    }
    try:
        response = httpx.post(
            f"{_agent_runtime_url()}/v1/agent/plan",
            json=agent_payload,
            timeout=5.0,
        )
        response.raise_for_status()
        plan = response.json()
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Agent runtime unavailable",
        ) from exc
    if plan.get("status") != "planned":
        audit_event(
            "event.webhook",
            "deny",
            {"event_type": payload.event_type, "reason": plan.get("refusal_reason")},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"refusal_reason": plan.get("refusal_reason")},
        )

    plan_steps = plan.get("plan", [])
    tool_calls = plan.get("tool_calls", [])
    trail.append(
        {
            "step": "agent_plan",
            "actor": "event_response_coordinator",
            "status": "planned",
            "details": {"plan_steps": len(plan_steps), "tool_calls": len(tool_calls)},
            "timestamp": _utcnow().isoformat(),
        }
    )

    eval_result = evaluate_agent_run(
        goal, payload.environment, ["plugin_gateway.invoke"], documents
    )
    approval_id: str | None = None
    with session_scope() as session:
        ingest = EventIngest(
            event_type=payload.event_type,
            severity=payload.severity,
            summary=payload.summary,
            source=payload.source,
            details=payload.details,
            environment=payload.environment,
            status="planned",
            correlation_id=correlation_id,
            tenant_id=payload.tenant_id,
            received_at=_utcnow(),
        )
        session.add(ingest)
        session.flush()
        run = AgentRun(
            goal=goal,
            environment=payload.environment,
            status="evaluating",
            plan=plan,
            requested_by=actor_id,
            correlation_id=correlation_id,
            tenant_id=payload.tenant_id,
        )
        session.add(run)
        session.flush()
        ingest.agent_run_id = run.id

        evaluation = AgentEvaluation(
            agent_run_id=run.id,
            score=eval_result.score,
            verdict=eval_result.verdict,
            reasons={"items": eval_result.reasons},
            correlation_id=correlation_id,
            actor_id=actor_id,
            tenant_id=payload.tenant_id,
        )
        session.add(evaluation)

        trail.append(
            {
                "step": "agent_evaluation",
                "actor": "agent_evaluator",
                "status": eval_result.verdict,
                "details": {"score": eval_result.score, "reasons": eval_result.reasons},
                "timestamp": _utcnow().isoformat(),
            }
        )

        if eval_result.verdict == "require_approval":
            run.status = "pending_approval"
            approval = Approval(
                agent_run_id=run.id,
                target_type="agent_run",
                requested_by=actor_id,
                required_role="approver",
                risk_level="high",
                rationale="Event response requires human approval.",
                plan_summary=f"Event response: {payload.summary}",
                artifacts={"event_type": payload.event_type, "severity": payload.severity},
                status="pending",
                correlation_id=correlation_id,
                tenant_id=payload.tenant_id,
            )
            session.add(approval)
            session.flush()
            approval_id = str(approval.id)
            ingest.approval_id = approval.id
            ingest.status = "pending_approval"
            trail.append(
                {
                    "step": "approval_requested",
                    "actor": actor_id,
                    "status": "pending",
                    "details": {"approval_id": approval_id},
                    "timestamp": _utcnow().isoformat(),
                }
            )
        elif eval_result.verdict == "deny":
            run.status = "denied"
            ingest.status = "denied"
        else:
            run.status = "planned"
            ingest.status = "planned"

        ingest.actions = {
            "plan_steps": plan_steps,
            "tool_calls": tool_calls,
            "policy": {
                "allow": decision.allow,
                "deny_reasons": decision.deny_reasons,
                "required_approvals": decision.required_approvals,
            },
            "evaluation": {
                "score": eval_result.score,
                "verdict": eval_result.verdict,
                "reasons": eval_result.reasons,
            },
            "approval": {"id": approval_id} if approval_id else None,
            "trail": trail,
        }

        audit_event(
            "event.webhook",
            "allow",
            {
                "event_type": payload.event_type,
                "severity": payload.severity,
                "agent_run_id": str(run.id),
                "approval_id": approval_id,
            },
            session=session,
        )
        session.flush()

    if eval_result.verdict == "deny":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"reasons": eval_result.reasons, "score": eval_result.score},
        )
    return {
        "status": "accepted",
        "agent_run_id": str(run.id),
        "approval_id": approval_id,
    }


@router.get("")
def list_events(ctx=require_permission("audit:read")) -> list[dict[str, Any]]:
    with session_scope() as session:
        ingests = (
            session.query(EventIngest)
            .filter(EventIngest.tenant_id == ctx.tenant_id)
            .order_by(EventIngest.received_at.desc())
            .limit(200)
            .all()
        )
        runtime_rows = (
            session.query(RuntimeEvent, RuntimeRun.environment)
            .outerjoin(RuntimeRun, RuntimeRun.id == RuntimeEvent.run_id)
            .filter(RuntimeEvent.tenant_id == ctx.tenant_id)
            .order_by(RuntimeEvent.occurred_at.desc())
            .limit(400)
            .all()
        )
        return _merge_events(ingests=ingests, runtime_rows=runtime_rows)[:200]


def _parse_since(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    cleaned = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid since"
        ) from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


_RUNTIME_EVENT_TO_INGEST_STATUS: dict[str, str] = {
    "run.started": "running",
    "plan.step.proposed": "running",
    "agent.message.sent": "running",
    "policy.decision.recorded": "running",
    "approval.requested": "pending_approval",
    "approval.resolved": "approved",
    "tool.call.started": "running",
    "tool.call.retrying": "running",
    "tool.call.completed": "completed",
    "tool.call.failed": "failed",
    "run.succeeded": "completed",
    "run.failed": "failed",
    "run.aborted": "aborted",
}

_RUNTIME_EVENT_TO_INGEST_SEVERITY: dict[str, str] = {
    "run.failed": "high",
    "run.aborted": "medium",
    "tool.call.failed": "high",
    "approval.requested": "medium",
}


def _runtime_event_status(event_type: str, payload: dict[str, Any]) -> str:
    if event_type == "policy.decision.recorded":
        outcome = str(payload.get("outcome", "")).strip().lower()
        if outcome == "deny":
            return "denied"
        if outcome == "pause":
            return "pending_approval"
    if event_type == "approval.resolved":
        outcome = str(payload.get("outcome", "")).strip().lower()
        if outcome:
            return outcome
    return _RUNTIME_EVENT_TO_INGEST_STATUS.get(event_type, "running")


def _runtime_event_severity(event_type: str) -> str:
    return _RUNTIME_EVENT_TO_INGEST_SEVERITY.get(event_type, "info")


def _runtime_event_summary(event_type: str, payload: dict[str, Any]) -> str:
    message = payload.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    if event_type == "policy.decision.recorded":
        outcome = str(payload.get("outcome", "unknown")).strip().lower() or "unknown"
        return f"Policy decision recorded ({outcome})."
    if event_type == "plan.step.proposed":
        return "Execution plan step proposed."
    if event_type == "tool.call.started":
        return "Tool invocation started."
    if event_type == "tool.call.retrying":
        return "Tool invocation retrying."
    if event_type == "tool.call.completed":
        return "Tool invocation completed."
    if event_type == "tool.call.failed":
        return "Tool invocation failed."
    if event_type == "run.started":
        return "Workflow run started."
    if event_type == "run.succeeded":
        return "Workflow run succeeded."
    if event_type == "run.failed":
        return "Workflow run failed."
    if event_type == "run.aborted":
        return "Workflow run aborted."
    return f"Runtime event: {event_type}"


def _event_ingest_to_payload(item: EventIngest) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "event_type": item.event_type,
        "severity": item.severity,
        "summary": item.summary,
        "source": item.source,
        "details": item.details,
        "environment": item.environment,
        "status": item.status,
        "agent_run_id": str(item.agent_run_id) if item.agent_run_id else None,
        "approval_id": str(item.approval_id) if item.approval_id else None,
        "actions": item.actions,
        "correlation_id": item.correlation_id,
        "received_at": item.received_at.isoformat(),
    }


def _runtime_event_to_payload(event: RuntimeEvent, environment: str) -> dict[str, Any]:
    envelope = event.envelope if isinstance(event.envelope, dict) else {}
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    return {
        "id": f"runtime:{event.id}",
        "event_type": event.event_type,
        "severity": _runtime_event_severity(event.event_type),
        "summary": _runtime_event_summary(event.event_type, payload),
        "source": "runtime-orchestrator",
        "details": {
            "runtime_event_id": event.event_id,
            "run_id": str(event.run_id),
            "step_id": str(event.step_id) if event.step_id else None,
            "payload": payload,
            "actor_id": event.actor_id,
            "tenant_id": event.tenant_id,
        },
        "environment": environment,
        "status": _runtime_event_status(event.event_type, payload),
        "agent_run_id": None,
        "approval_id": None,
        "actions": {
            "runtime_event_id": event.event_id,
            "event_type": event.event_type,
            "schema_version": event.schema_version or "v1",
        },
        "correlation_id": event.correlation_id,
        "received_at": event.occurred_at.isoformat(),
    }


def _merge_events(
    *,
    ingests: list[EventIngest],
    runtime_rows: list[Any],
) -> list[dict[str, Any]]:
    mirrored_runtime_ids = {
        str((item.details or {}).get("runtime_event_id")).strip()
        for item in ingests
        if item.source == "runtime-orchestrator"
        and isinstance(item.details, dict)
        and (item.details or {}).get("runtime_event_id")
    }
    merged = [_event_ingest_to_payload(item) for item in ingests]
    for runtime_event, run_environment in runtime_rows:
        if runtime_event.event_id in mirrored_runtime_ids:
            continue
        merged.append(_runtime_event_to_payload(runtime_event, run_environment or "dev"))
    merged.sort(key=lambda item: item["received_at"], reverse=True)
    return merged


@router.get("/stream")
def stream_events(
    since: str | None = None,
    once: bool = False,
    ctx=require_permission("audit:read"),
) -> StreamingResponse:
    if once and not since:
        since_ts = datetime.fromtimestamp(0, tz=timezone.utc)
    else:
        since_ts = _parse_since(since)

    async def _event_stream():
        last_ts = since_ts
        last_id: str | None = None
        while True:
            with session_scope() as session:
                ingests = (
                    session.query(EventIngest)
                    .filter(
                        EventIngest.tenant_id == ctx.tenant_id,
                        EventIngest.received_at >= last_ts,
                    )
                    .order_by(EventIngest.received_at.asc())
                    .limit(200)
                    .all()
                )
                runtime_rows = (
                    session.query(RuntimeEvent, RuntimeRun.environment)
                    .outerjoin(RuntimeRun, RuntimeRun.id == RuntimeEvent.run_id)
                    .filter(
                        RuntimeEvent.tenant_id == ctx.tenant_id,
                        RuntimeEvent.occurred_at >= last_ts,
                    )
                    .order_by(RuntimeEvent.occurred_at.asc())
                    .limit(200)
                    .all()
                )
                payloads = _merge_events(ingests=ingests, runtime_rows=runtime_rows)
                payloads.sort(key=lambda item: item["received_at"])
                for payload in payloads:
                    item_id = payload["id"]
                    if last_id == item_id:
                        continue
                    last_id = item_id
                    last_ts = _parse_since(str(payload["received_at"]))
                    yield f"id: {item_id}\n"
                    yield f"data: {json.dumps(payload)}\n\n"
            if once:
                break
            yield ": heartbeat\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(_event_stream(), media_type="text/event-stream")
