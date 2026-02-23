from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, cast

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel, Field

from apps.api.app.db import session_scope
from apps.api.app.models import AuditEvent, RuntimeEvent, RuntimeRun, RuntimeStep
from apps.api.app.runtime_store import RuntimeStore
from libs.common.metrics import render_metrics
from libs.common.otel import init_otel, instrument_fastapi

from .event_bus import JetStreamPublisher
from .temporal_engine import TemporalStarter

app = FastAPI(title="Autonoma Runtime Orchestrator", version="0.0.0")
init_otel(os.getenv("SERVICE_NAME", "runtime-orchestrator"))
instrument_fastapi(app)


class RunContext(BaseModel):
    correlation_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    actor_name: str | None = None


class OrchestratorRunCreateRequest(BaseModel):
    intent: str = Field(min_length=1)
    environment: Literal["dev", "stage", "prod"]
    metadata: dict[str, Any] = Field(default_factory=dict)
    context: RunContext


class OrchestratorRunCreateResponse(BaseModel):
    run_id: str
    status: str
    summary: str
    correlation_id: str
    actor_id: str
    tenant_id: str


class OrchestratorRunResponse(BaseModel):
    run_id: str
    status: str
    intent: str
    environment: str
    created_at: str
    updated_at: str
    correlation_id: str
    actor_id: str
    tenant_id: str
    steps: list[dict[str, Any]]


class OrchestratorTimelineResponse(BaseModel):
    run_id: str
    events: list[dict[str, Any]]


class PolicyGateRequest(BaseModel):
    run_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    retry_count: int = Field(default=0, ge=0)
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    requires_human_approval: bool = False
    correlation_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)


class PolicyGateResponse(BaseModel):
    allow: bool
    outcome: Literal["allow", "deny", "pause"]
    reasons: list[str]
    required_approvals: list[str]
    decision_artifact_id: str


class ToolExecutionRequest(BaseModel):
    plugin: str = Field(min_length=1)
    action: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class ToolExecutionResult(BaseModel):
    ok: bool
    normalized_outcome: Literal[
        "success",
        "transient",
        "permanent",
        "policy_denied",
        "approval_required",
    ]
    status_code: int | None = None
    response_payload: dict[str, Any] = Field(default_factory=dict)
    error_detail: str | None = None
    terminal: bool = True


_NORMALIZED_TOOL_OUTCOMES = {
    "success",
    "transient",
    "permanent",
    "policy_denied",
    "approval_required",
}

_RUNTIME_EVENT_TO_INGEST_STATUS: dict[str, str] = {
    "run.started": "running",
    "plan.step.proposed": "planned",
    "policy.decision.recorded": "planned",
    "approval.requested": "pending_approval",
    "approval.resolved": "completed",
    "tool.call.started": "running",
    "tool.call.retrying": "running",
    "tool.call.completed": "completed",
    "tool.call.failed": "failed",
    "run.succeeded": "succeeded",
    "run.failed": "failed",
    "run.aborted": "aborted",
}

_RUNTIME_EVENT_TO_INGEST_SEVERITY: dict[str, str] = {
    "tool.call.failed": "high",
    "run.failed": "high",
    "run.aborted": "medium",
    "policy.decision.recorded": "medium",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _require_service_token(request: Request) -> None:
    expected = os.getenv("SERVICE_TOKEN")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Missing token",
        )
    token = request.headers.get("x-service-token")
    if token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def _require_tenant_scope(tenant_id: str | None) -> str:
    value = str(tenant_id or "").strip()
    if not value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tenant_id")
    return value


def _event_bus() -> JetStreamPublisher:
    return JetStreamPublisher(
        enabled=os.getenv("RUNTIME_ORCHESTRATOR_ENABLE_EVENT_BUS", "false").lower() == "true",
        nats_url=os.getenv("NATS_URL", "nats://nats:4222"),
        subject=os.getenv("RUNTIME_EVENTS_SUBJECT", "runtime.events"),
        stream_name=os.getenv("RUNTIME_EVENTS_STREAM", "runtime_events"),
    )


def _temporal() -> TemporalStarter:
    return TemporalStarter(
        enabled=os.getenv("RUNTIME_ORCHESTRATOR_ENABLE_TEMPORAL", "false").lower() == "true",
        address=os.getenv("TEMPORAL_ADDRESS", "temporal:7233"),
        task_queue=os.getenv("TEMPORAL_TASK_QUEUE", "runtime-orchestrator"),
    )


def _plugin_gateway_url() -> str:
    return os.getenv("PLUGIN_GATEWAY_URL", "http://plugin-gateway:8002/invoke").rstrip("/")


def _tool_retry_config() -> tuple[int, float]:
    raw_retries = os.getenv("RUNTIME_TOOL_MAX_RETRIES", "2")
    raw_backoff = os.getenv("RUNTIME_TOOL_RETRY_BACKOFF_SECONDS", "0.1")
    try:
        max_retries = max(0, int(raw_retries))
    except ValueError:
        max_retries = 2
    try:
        backoff_seconds = max(0.0, float(raw_backoff))
    except ValueError:
        backoff_seconds = 0.1
    return max_retries, backoff_seconds


def _policy_gate_url() -> str:
    return os.getenv(
        "RUNTIME_POLICY_GATE_URL",
        "http://api:8000/v1/internal/policy/step-evaluate",
    ).rstrip("/")


def _policy_failure_mode() -> Literal["pause", "deny"]:
    configured = os.getenv("RUNTIME_POLICY_FAILURE_MODE", "pause").strip().lower()
    if configured == "deny":
        return "deny"
    return "pause"


def _evaluate_step_policy(
    *,
    payload: PolicyGateRequest,
    service_token: str,
) -> PolicyGateResponse:
    try:
        response = httpx.post(
            _policy_gate_url(),
            headers={"x-service-token": service_token},
            json=payload.model_dump(),
            timeout=2.5,
        )
        response.raise_for_status()
        return PolicyGateResponse.model_validate(response.json())
    except (httpx.HTTPError, ValueError):
        failure_mode = _policy_failure_mode()
        if failure_mode == "deny":
            return PolicyGateResponse(
                allow=False,
                outcome="deny",
                reasons=["policy_unavailable"],
                required_approvals=[],
                decision_artifact_id=(
                    f"artifact:{payload.run_id}:{payload.step_id}:deny:policy-unavailable"
                ),
            )
        return PolicyGateResponse(
            allow=False,
            outcome="pause",
            reasons=["policy_unavailable"],
            required_approvals=["approver"],
            decision_artifact_id=(
                f"artifact:{payload.run_id}:{payload.step_id}:pause:policy-unavailable"
            ),
        )


def _record_policy_audit(
    *,
    session: Any,
    actor_id: str,
    tenant_id: str,
    correlation_id: str,
    run_id: uuid.UUID,
    step_id: uuid.UUID,
    decision: PolicyGateResponse,
) -> None:
    audit = AuditEvent(
        event_type="policy",
        outcome=decision.outcome,
        source="runtime-orchestrator",
        details={
            "action": "step.execute",
            "run_id": str(run_id),
            "step_id": str(step_id),
            "reasons": decision.reasons,
            "required_approvals": decision.required_approvals,
            "decision_artifact_id": decision.decision_artifact_id,
        },
        correlation_id=correlation_id,
        actor_id=actor_id,
        tenant_id=tenant_id,
    )
    session.add(audit)


def _invoke_plugin_gateway(
    *,
    request_payload: ToolExecutionRequest,
    context: RunContext,
    service_token: str,
) -> ToolExecutionResult:
    try:
        response = httpx.post(
            _plugin_gateway_url(),
            headers={"x-service-token": service_token},
            json={
                "plugin": request_payload.plugin,
                "action": request_payload.action,
                "params": request_payload.params,
                "context": {
                    "correlation_id": context.correlation_id,
                    "actor_id": context.actor_id,
                    "tenant_id": context.tenant_id,
                },
            },
            timeout=5.0,
        )
        if response.status_code < 400:
            payload = response.json()
            response_status = ""
            if isinstance(payload, dict):
                response_status = str(payload.get("status") or "").strip().lower()
            terminal = response_status not in {"submitted", "running", "queued", "pending"}
            return ToolExecutionResult(
                ok=True,
                normalized_outcome="success",
                status_code=response.status_code,
                response_payload=payload if isinstance(payload, dict) else {"result": payload},
                terminal=terminal,
            )
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/json"):
            detail = response.json()
        else:
            detail = {"detail": response.text}
        if response.status_code == 403:
            required = detail.get("required_approvals", []) if isinstance(detail, dict) else []
            if required:
                return ToolExecutionResult(
                    ok=False,
                    normalized_outcome="approval_required",
                    status_code=403,
                    response_payload={"detail": detail},
                    error_detail="approval_required",
                    terminal=True,
                )
            return ToolExecutionResult(
                ok=False,
                normalized_outcome="policy_denied",
                status_code=403,
                response_payload={"detail": detail},
                error_detail="policy_denied",
                terminal=True,
            )
        if response.status_code in {429, 502, 503, 504}:
            return ToolExecutionResult(
                ok=False,
                normalized_outcome="transient",
                status_code=response.status_code,
                response_payload={"detail": detail},
                error_detail="transient_gateway_error",
                terminal=False,
            )
        return ToolExecutionResult(
            ok=False,
            normalized_outcome="permanent",
            status_code=response.status_code,
            response_payload={"detail": detail},
            error_detail="permanent_gateway_error",
            terminal=True,
        )
    except (
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
    ) as exc:
        return ToolExecutionResult(
            ok=False,
            normalized_outcome="transient",
            response_payload={"detail": str(exc)},
            error_detail="plugin_gateway_unavailable",
            terminal=False,
        )
    except ValueError as exc:
        return ToolExecutionResult(
            ok=False,
            normalized_outcome="permanent",
            response_payload={"detail": str(exc)},
            error_detail="invalid_gateway_response",
            terminal=True,
        )


def _parse_execution_request(metadata: dict[str, Any]) -> ToolExecutionRequest | None:
    raw = metadata.get("execution")
    if not isinstance(raw, dict):
        return None
    plugin = str(raw.get("plugin", "")).strip()
    action = str(raw.get("action", "")).strip()
    if not plugin or not action:
        return None
    params = raw.get("params", {})
    if not isinstance(params, dict):
        params = {}
    return ToolExecutionRequest(plugin=plugin, action=action, params=params)


def _coerce_normalized_outcome(value: str, *, default: str) -> Literal[
    "success",
    "transient",
    "permanent",
    "policy_denied",
    "approval_required",
]:
    candidate = value if value in _NORMALIZED_TOOL_OUTCOMES else default
    return cast(
        Literal[
            "success",
            "transient",
            "permanent",
            "policy_denied",
            "approval_required",
        ],
        candidate,
    )


def _execute_step_via_broker(
    *,
    store: RuntimeStore,
    run: RuntimeRun,
    step: RuntimeStep,
    context: RunContext,
    service_token: str,
    execution_request: ToolExecutionRequest,
) -> ToolExecutionResult:
    max_retries, backoff_seconds = _tool_retry_config()
    last_result = ToolExecutionResult(ok=False, normalized_outcome="permanent")
    base_key = f"{run.id}:{step.id}:{execution_request.plugin}:{execution_request.action}"
    for attempt in range(0, max_retries + 1):
        idempotency_key = f"{base_key}:{attempt}"
        if attempt == 0:
            _append_event(
                store,
                run_id=run.id,
                step_id=step.id,
                event_type="tool.call.started",
                correlation_id=context.correlation_id,
                actor_id=context.actor_id,
                tenant_id=context.tenant_id,
                agent_id="event_response_worker",
                payload={
                    "plugin": execution_request.plugin,
                    "action": execution_request.action,
                    "attempt": attempt,
                    "idempotency_key": idempotency_key,
                },
                environment=run.environment,
            )
        else:
            _append_event(
                store,
                run_id=run.id,
                step_id=step.id,
                event_type="tool.call.retrying",
                correlation_id=context.correlation_id,
                actor_id=context.actor_id,
                tenant_id=context.tenant_id,
                agent_id="event_response_worker",
                payload={
                    "plugin": execution_request.plugin,
                    "action": execution_request.action,
                    "attempt": attempt,
                    "idempotency_key": idempotency_key,
                },
                environment=run.environment,
            )

        existing = store.get_tool_invocation(
            tenant_id=context.tenant_id,
            idempotency_key=idempotency_key,
        )
        if existing is None:
            existing = store.record_tool_invocation(
                run_id=run.id,
                step_id=step.id,
                tool_name="plugin_gateway",
                action=execution_request.action,
                idempotency_key=idempotency_key,
                status="started",
                request_payload={
                    "plugin": execution_request.plugin,
                    "action": execution_request.action,
                    "params": execution_request.params,
                },
                response_payload={},
                correlation_id=context.correlation_id,
                actor_id=context.actor_id,
                tenant_id=context.tenant_id,
                retry_count=attempt,
            )
        elif existing.status in {"completed", "failed"}:
            default_outcome = "success" if existing.status == "completed" else "permanent"
            return ToolExecutionResult(
                ok=existing.status == "completed",
                normalized_outcome=_coerce_normalized_outcome(
                    existing.normalized_outcome or default_outcome,
                    default=default_outcome,
                ),
                response_payload=existing.response_payload or {},
                terminal=True,
            )

        result = _invoke_plugin_gateway(
            request_payload=execution_request,
            context=context,
            service_token=service_token,
        )
        store.update_tool_invocation(
            invocation=existing,
            status="completed" if result.ok else "failed",
            retry_count=attempt,
            normalized_outcome=result.normalized_outcome,
            response_payload=result.response_payload,
        )
        if result.ok:
            _append_event(
                store,
                run_id=run.id,
                step_id=step.id,
                event_type="tool.call.completed",
                correlation_id=context.correlation_id,
                actor_id=context.actor_id,
                tenant_id=context.tenant_id,
                agent_id="event_response_worker",
                payload={
                    "plugin": execution_request.plugin,
                    "action": execution_request.action,
                    "attempt": attempt,
                    "idempotency_key": idempotency_key,
                    "normalized_outcome": result.normalized_outcome,
                    "response_payload": result.response_payload,
                },
                environment=run.environment,
            )
            return result
        last_result = result
        if result.normalized_outcome != "transient" or attempt >= max_retries:
            _append_event(
                store,
                run_id=run.id,
                step_id=step.id,
                event_type="tool.call.failed",
                correlation_id=context.correlation_id,
                actor_id=context.actor_id,
                tenant_id=context.tenant_id,
                agent_id="event_response_worker",
                payload={
                    "plugin": execution_request.plugin,
                    "action": execution_request.action,
                    "attempt": attempt,
                    "idempotency_key": idempotency_key,
                    "normalized_outcome": result.normalized_outcome,
                    "error": result.error_detail,
                },
                environment=run.environment,
            )
            return result
        if backoff_seconds > 0:
            time.sleep(backoff_seconds * (attempt + 1))
    return last_result


def _append_event(
    store: RuntimeStore,
    *,
    run_id: uuid.UUID,
    step_id: uuid.UUID | None,
    event_type: str,
    correlation_id: str,
    actor_id: str,
    tenant_id: str,
    agent_id: str,
    payload: dict[str, Any],
    environment: str = "dev",
) -> dict[str, Any]:
    event_id = f"{run_id}:{event_type}:{uuid.uuid4()}"
    occurred_at = _utcnow()
    envelope = {
        "event_id": event_id,
        "event_type": event_type,
        "schema_version": "v1",
        "run_id": str(run_id),
        "step_id": str(step_id) if step_id else None,
        "timestamp": occurred_at.isoformat(),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "payload": payload,
        "visibility_level": "tenant",
        "redaction": "none",
    }
    store.append_event(
        run_id=run_id,
        step_id=step_id,
        event_id=event_id,
        event_type=event_type,
        schema_version="v1",
        occurred_at=occurred_at,
        envelope=envelope,
        correlation_id=correlation_id,
        actor_id=actor_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        visibility_level="tenant",
        redaction="none",
    )
    store.append_event_ingest(
        event_type=event_type,
        severity=_event_ingest_severity(event_type),
        summary=_event_ingest_summary(event_type, payload),
        source="runtime-orchestrator",
        details={
            "runtime_event_id": event_id,
            "run_id": str(run_id),
            "step_id": str(step_id) if step_id else None,
            "payload": payload,
            "actor_id": actor_id,
            "agent_id": agent_id,
            "tenant_id": tenant_id,
        },
        environment=environment,
        status=_event_ingest_status(event_type, payload),
        actions={
            "runtime_event_id": event_id,
            "event_type": event_type,
            "schema_version": "v1",
        },
        correlation_id=correlation_id,
        tenant_id=tenant_id,
        received_at=occurred_at,
    )
    _event_bus().publish(envelope)
    return envelope


def _event_ingest_status(event_type: str, payload: dict[str, Any]) -> str:
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


def _event_ingest_severity(event_type: str) -> str:
    return _RUNTIME_EVENT_TO_INGEST_SEVERITY.get(event_type, "info")


def _event_ingest_summary(event_type: str, payload: dict[str, Any]) -> str:
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


def _canonical_timeline_event(event: RuntimeEvent) -> dict[str, Any]:
    envelope = event.envelope if isinstance(event.envelope, dict) else {}
    timestamp = envelope.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp.strip():
        timestamp = event.occurred_at.isoformat()
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    agent_id = envelope.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id.strip():
        agent_id = "unknown"
    visibility_level = envelope.get("visibility_level")
    if visibility_level not in {"internal", "tenant", "public"}:
        visibility_level = event.visibility_level or "tenant"
    redaction = envelope.get("redaction")
    if redaction not in {"none", "partial", "full"}:
        redaction = event.redaction or "none"
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "schema_version": event.schema_version or "v1",
        "run_id": str(event.run_id),
        "step_id": str(event.step_id) if event.step_id else None,
        "timestamp": timestamp,
        "correlation_id": event.correlation_id,
        "actor_id": event.actor_id,
        "tenant_id": event.tenant_id,
        "agent_id": agent_id,
        "payload": payload,
        "visibility_level": visibility_level,
        "redaction": redaction,
    }


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/metrics")
def metrics() -> Any:
    from fastapi import Response
    from prometheus_client import CONTENT_TYPE_LATEST

    return Response(content=render_metrics(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/orchestrator/runs", response_model=OrchestratorRunCreateResponse)
def create_run(
    payload: OrchestratorRunCreateRequest,
    request: Request,
) -> OrchestratorRunCreateResponse:
    _require_service_token(request)
    tenant_id = _require_tenant_scope(payload.context.tenant_id)
    service_token = os.getenv("SERVICE_TOKEN")
    if not service_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Missing token",
        )

    with session_scope() as session:
        store = RuntimeStore(session)
        run = store.create_run(
            intent=payload.intent,
            environment=payload.environment,
            requester_actor_id=payload.context.actor_id,
            requester_actor_name=payload.context.actor_name,
            tenant_id=tenant_id,
            correlation_id=payload.context.correlation_id,
            metadata=payload.metadata,
        )
        store.create_step(
            run_id=run.id,
            step_key="security_guardian_gate",
            assigned_agent="security_guardian_worker",
            tenant_id=tenant_id,
            correlation_id=payload.context.correlation_id,
        )
        plan_step = store.create_step(
            run_id=run.id,
            step_key="reasoning_plan",
            assigned_agent="reasoning_worker",
            tenant_id=tenant_id,
            correlation_id=payload.context.correlation_id,
        )

        _append_event(
            store,
            run_id=run.id,
            step_id=None,
            event_type="run.started",
            correlation_id=payload.context.correlation_id,
            actor_id=payload.context.actor_id,
            tenant_id=tenant_id,
            agent_id="orchestrator_worker",
            payload={"message": "Run created and queued for orchestration."},
            environment=run.environment,
        )
        _append_event(
            store,
            run_id=run.id,
            step_id=plan_step.id,
            event_type="plan.step.proposed",
            correlation_id=payload.context.correlation_id,
            actor_id=payload.context.actor_id,
            tenant_id=tenant_id,
            agent_id="reasoning_worker",
            payload={"step": "Build execution plan for requested intent."},
            environment=run.environment,
        )

        policy_request = PolicyGateRequest(
            run_id=str(run.id),
            step_id=str(plan_step.id),
            action=f"step.execute.{plan_step.step_key}",
            retry_count=plan_step.retry_count,
            risk_score=float(payload.metadata.get("risk_score", 0.1)),
            requires_human_approval=bool(payload.metadata.get("requires_human_approval", False)),
            correlation_id=payload.context.correlation_id,
            actor_id=payload.context.actor_id,
            tenant_id=tenant_id,
        )
        decision = _evaluate_step_policy(payload=policy_request, service_token=service_token)
        _append_event(
            store,
            run_id=run.id,
            step_id=plan_step.id,
            event_type="policy.decision.recorded",
            correlation_id=payload.context.correlation_id,
            actor_id=payload.context.actor_id,
            tenant_id=tenant_id,
            agent_id="security_guardian_worker",
            payload={
                "outcome": decision.outcome,
                "allow": decision.allow,
                "reasons": decision.reasons,
                "required_approvals": decision.required_approvals,
                "decision_artifact_id": decision.decision_artifact_id,
            },
            environment=run.environment,
        )
        _record_policy_audit(
            session=session,
            actor_id=payload.context.actor_id,
            tenant_id=tenant_id,
            correlation_id=payload.context.correlation_id,
            run_id=run.id,
            step_id=plan_step.id,
            decision=decision,
        )

        summary = "Run accepted and dispatched to orchestrator workers."
        if decision.outcome == "allow":
            plan_step.gate_status = "allowed"
            plan_step.status = "executing"
            plan_step.approval_status = "not_required"
            run.status = "running"
        elif decision.outcome == "pause":
            plan_step.gate_status = "paused"
            plan_step.status = "paused"
            plan_step.approval_status = "required"
            run.status = "paused"
            summary = "Run paused pending guardian/policy decision or approval."
        else:
            plan_step.gate_status = "denied"
            plan_step.status = "blocked"
            plan_step.approval_status = "not_required"
            run.status = "failed"
            summary = "Run blocked by guardian/policy decision."
        plan_step.updated_at = _utcnow()
        execution_request = _parse_execution_request(payload.metadata)
        if execution_request is not None and decision.outcome == "allow":
            execution_request.params = {
                **execution_request.params,
                "_autonoma": {
                    "runtime_run_id": str(run.id),
                    "tenant_id": tenant_id,
                    "correlation_id": payload.context.correlation_id,
                },
            }
            broker_result = _execute_step_via_broker(
                store=store,
                run=run,
                step=plan_step,
                context=payload.context,
                service_token=service_token,
                execution_request=execution_request,
            )
            if broker_result.ok:
                plan_step.status = "completed"
                if broker_result.terminal:
                    run.status = "succeeded"
                    _append_event(
                        store,
                        run_id=run.id,
                        step_id=plan_step.id,
                        event_type="run.succeeded",
                        correlation_id=payload.context.correlation_id,
                        actor_id=payload.context.actor_id,
                        tenant_id=tenant_id,
                        agent_id="orchestrator_worker",
                        payload={"message": "Run completed via execution broker."},
                        environment=run.environment,
                    )
                    summary = "Run completed via Plugin Gateway execution broker."
                else:
                    run.status = "running"
                    summary = "Run accepted and waiting for external workflow completion callback."
            else:
                plan_step.status = "failed"
                run.status = "failed"
                _append_event(
                    store,
                    run_id=run.id,
                    step_id=plan_step.id,
                    event_type="run.failed",
                    correlation_id=payload.context.correlation_id,
                    actor_id=payload.context.actor_id,
                    tenant_id=tenant_id,
                    agent_id="orchestrator_worker",
                    payload={
                        "message": "Run failed during Plugin Gateway execution.",
                        "normalized_outcome": broker_result.normalized_outcome,
                        "error": broker_result.error_detail,
                    },
                    environment=run.environment,
                )
                summary = (
                    "Run failed during Plugin Gateway execution "
                    f"({broker_result.normalized_outcome})."
                )
        run.updated_at = _utcnow()
        session.flush()

        _temporal().start_run_workflow(
            run_id=str(run.id),
            payload={
                "run_id": str(run.id),
                "intent": run.intent,
                "tenant_id": run.tenant_id,
                "correlation_id": run.correlation_id,
            },
        )

        return OrchestratorRunCreateResponse(
            run_id=str(run.id),
            status=run.status,
            summary=summary,
            correlation_id=run.correlation_id,
            actor_id=run.requester_actor_id,
            tenant_id=run.tenant_id,
        )


@app.get("/v1/orchestrator/runs/{run_id}", response_model=OrchestratorRunResponse)
def get_run(run_id: str, tenant_id: str, request: Request) -> OrchestratorRunResponse:
    _require_service_token(request)
    scoped_tenant = _require_tenant_scope(tenant_id)
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid run_id",
        ) from exc

    with session_scope() as session:
        run = (
            session.query(RuntimeRun)
            .filter(RuntimeRun.id == run_uuid, RuntimeRun.tenant_id == scoped_tenant)
            .one_or_none()
        )
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        steps = (
            session.query(RuntimeStep)
            .filter(RuntimeStep.run_id == run.id, RuntimeStep.tenant_id == scoped_tenant)
            .order_by(RuntimeStep.created_at.asc())
            .all()
        )
        return OrchestratorRunResponse(
            run_id=str(run.id),
            status=run.status,
            intent=run.intent,
            environment=run.environment,
            created_at=run.created_at.isoformat(),
            updated_at=run.updated_at.isoformat(),
            correlation_id=run.correlation_id,
            actor_id=run.requester_actor_id,
            tenant_id=run.tenant_id,
            steps=[
                {
                    "step_id": str(step.id),
                    "step_key": step.step_key,
                    "status": step.status,
                    "assigned_agent": step.assigned_agent,
                    "gate_status": step.gate_status,
                    "approval_status": step.approval_status,
                    "retry_count": step.retry_count,
                }
                for step in steps
            ],
        )


@app.get("/v1/orchestrator/runs/{run_id}/timeline", response_model=OrchestratorTimelineResponse)
def get_timeline(run_id: str, tenant_id: str, request: Request) -> OrchestratorTimelineResponse:
    _require_service_token(request)
    scoped_tenant = _require_tenant_scope(tenant_id)
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid run_id",
        ) from exc

    with session_scope() as session:
        store = RuntimeStore(session)
        run = store.get_run(run_id=run_uuid, tenant_id=scoped_tenant)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        events = store.list_events(run_id=run_uuid, tenant_id=scoped_tenant)
        return OrchestratorTimelineResponse(
            run_id=run_id,
            events=[_canonical_timeline_event(event) for event in events],
        )
