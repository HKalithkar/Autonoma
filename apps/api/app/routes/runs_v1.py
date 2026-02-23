from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from libs.common.context import get_request_context

from ..audit import audit_event
from ..rbac import require_permission

router = APIRouter(prefix="/v1", tags=["runs-v1"])


def _require_service_token(request: Request) -> None:
    token = request.headers.get("x-service-token")
    expected = os.getenv("SERVICE_TOKEN")
    if not token or not expected or token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def _orchestrator_url() -> str:
    return os.getenv("RUNTIME_ORCHESTRATOR_URL", "http://runtime-orchestrator:8003").rstrip("/")


def _orchestrator_headers() -> dict[str, str]:
    token = os.getenv("SERVICE_TOKEN")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Missing SERVICE_TOKEN",
        )
    return {"x-service-token": token}


class RunCreateRequest(BaseModel):
    intent: str = Field(min_length=1)
    environment: Literal["dev", "stage", "prod"]
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunCreateResponse(BaseModel):
    run_id: str
    status: str
    summary: str
    correlation_id: str
    actor_id: str
    tenant_id: str


class RunSummaryResponse(BaseModel):
    run_id: str
    status: str
    intent: str
    environment: str
    created_at: str
    updated_at: str
    correlation_id: str
    actor_id: str
    tenant_id: str


class TimelineEvent(BaseModel):
    event_id: str
    event_type: str
    schema_version: str
    run_id: str
    step_id: str | None = None
    timestamp: str
    correlation_id: str
    actor_id: str
    tenant_id: str
    agent_id: str
    payload: dict[str, Any]
    visibility_level: Literal["internal", "tenant", "public"] = "tenant"
    redaction: Literal["none", "partial", "full"] = "none"


class TimelineResponse(BaseModel):
    run_id: str
    events: list[TimelineEvent]
    next_event_id: str | None = None


class ApprovalDecisionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ApprovalDecisionResponse(BaseModel):
    run_id: str
    status: str
    decision: Literal["approved", "rejected"]
    actor_id: str
    correlation_id: str


class StepPolicyEvaluateRequest(BaseModel):
    run_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    retry_count: int = Field(default=0, ge=0)
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    requires_human_approval: bool = False
    correlation_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)


class StepPolicyEvaluateResponse(BaseModel):
    allow: bool
    outcome: Literal["allow", "deny", "pause"]
    reasons: list[str]
    required_approvals: list[str]
    decision_artifact_id: str


def _event_sort_key(event: TimelineEvent) -> tuple[datetime, str]:
    ts = event.timestamp
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return (datetime.fromisoformat(ts), event.event_id)


def _filter_events_after(
    events: list[TimelineEvent],
    *,
    after_event_id: str | None,
) -> list[TimelineEvent]:
    if not after_event_id:
        return events
    seen_cursor = False
    filtered: list[TimelineEvent] = []
    for event in events:
        if seen_cursor:
            filtered.append(event)
            continue
        if event.event_id == after_event_id:
            seen_cursor = True
    if seen_cursor:
        return filtered
    return events



@router.post(
    "/runs",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RunCreateResponse,
)
def create_run_v1(
    payload: RunCreateRequest,
    ctx=require_permission("agent:run"),
) -> RunCreateResponse:
    context = get_request_context()
    try:
        response = httpx.post(
            f"{_orchestrator_url()}/v1/orchestrator/runs",
            headers=_orchestrator_headers(),
            json={
                "intent": payload.intent,
                "environment": payload.environment,
                "metadata": payload.metadata,
                "context": {
                    "correlation_id": context.correlation_id,
                    "actor_id": ctx.actor_id,
                    "tenant_id": ctx.tenant_id,
                    "actor_name": ctx.username,
                },
            },
            timeout=5.0,
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Runtime orchestrator unavailable",
        ) from exc
    return RunCreateResponse(**data)


@router.get("/runs/{run_id}", response_model=RunSummaryResponse)
def get_run_v1(run_id: str, ctx=require_permission("workflow:read")) -> RunSummaryResponse:
    del ctx
    context = get_request_context()
    try:
        response = httpx.get(
            f"{_orchestrator_url()}/v1/orchestrator/runs/{run_id}",
            headers=_orchestrator_headers(),
            params={"tenant_id": context.tenant_id},
            timeout=5.0,
        )
        if response.status_code == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        response.raise_for_status()
        payload = response.json()
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Runtime orchestrator unavailable",
        ) from exc
    return RunSummaryResponse(
        run_id=payload["run_id"],
        status=payload["status"],
        intent=payload["intent"],
        environment=payload["environment"],
        created_at=payload["created_at"],
        updated_at=payload["updated_at"],
        correlation_id=payload["correlation_id"],
        actor_id=payload["actor_id"],
        tenant_id=payload["tenant_id"],
    )


@router.get("/runs/{run_id}/timeline", response_model=TimelineResponse)
def get_run_timeline_v1(
    run_id: str,
    after_event_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    ctx=require_permission("workflow:read"),
) -> TimelineResponse:
    del ctx
    context = get_request_context()
    try:
        response = httpx.get(
            f"{_orchestrator_url()}/v1/orchestrator/runs/{run_id}/timeline",
            headers=_orchestrator_headers(),
            params={"tenant_id": context.tenant_id},
            timeout=5.0,
        )
        if response.status_code == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        response.raise_for_status()
        payload = response.json()
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Runtime orchestrator unavailable",
        ) from exc
    events = [TimelineEvent.model_validate(event) for event in payload["events"]]
    ordered = sorted(events, key=_event_sort_key)
    filtered = _filter_events_after(ordered, after_event_id=after_event_id)
    sliced = filtered[:limit]
    next_event_id = sliced[-1].event_id if sliced else after_event_id
    return TimelineResponse(run_id=payload["run_id"], events=sliced, next_event_id=next_event_id)


@router.get("/runs/{run_id}/stream")
def stream_run_v1(
    run_id: str,
    request: Request,
    last_event_id: str | None = None,
    follow_seconds: float = Query(default=10.0, ge=0.0, le=30.0),
    poll_interval_seconds: float = Query(default=1.0, ge=0.05, le=2.0),
    ctx=require_permission("workflow:read"),
) -> StreamingResponse:
    cursor = last_event_id or request.headers.get("last-event-id")

    async def _event_stream():
        current_cursor = cursor
        timeline = get_run_timeline_v1(
            run_id=run_id,
            after_event_id=current_cursor,
            limit=500,
            ctx=ctx,
        )
        for event in timeline.events:
            yield f"id: {event.event_id}\n"
            yield f"event: {event.event_type}\n"
            yield f"data: {event.model_dump_json()}\n\n"
            current_cursor = event.event_id

        if follow_seconds <= 0:
            return

        deadline = asyncio.get_running_loop().time() + follow_seconds
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(poll_interval_seconds)
            timeline = get_run_timeline_v1(
                run_id=run_id,
                after_event_id=current_cursor,
                limit=500,
                ctx=ctx,
            )
            for event in timeline.events:
                yield f"id: {event.event_id}\n"
                yield f"event: {event.event_type}\n"
                yield f"data: {event.model_dump_json()}\n\n"
                current_cursor = event.event_id

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


@router.post("/runs/{run_id}/approve", response_model=ApprovalDecisionResponse)
def approve_run_v1(
    run_id: str,
    payload: ApprovalDecisionRequest,
    ctx=require_permission("approval:write"),
) -> ApprovalDecisionResponse:
    del payload
    context = get_request_context()
    audit_event(
        "approval.decision",
        "allow",
        {
            "decision": "approve",
            "target_type": "workflow_run_v1",
            "workflow_run_id": run_id,
            "adapter": "v1_runtime",
        },
    )
    return ApprovalDecisionResponse(
        run_id=run_id,
        status="running",
        decision="approved",
        actor_id=ctx.actor_id,
        correlation_id=context.correlation_id,
    )


@router.post("/runs/{run_id}/reject", response_model=ApprovalDecisionResponse)
def reject_run_v1(
    run_id: str,
    payload: ApprovalDecisionRequest,
    ctx=require_permission("approval:write"),
) -> ApprovalDecisionResponse:
    del payload
    context = get_request_context()
    audit_event(
        "approval.decision",
        "deny",
        {
            "decision": "reject",
            "target_type": "workflow_run_v1",
            "workflow_run_id": run_id,
            "adapter": "v1_runtime",
        },
    )
    return ApprovalDecisionResponse(
        run_id=run_id,
        status="aborted",
        decision="rejected",
        actor_id=ctx.actor_id,
        correlation_id=context.correlation_id,
    )


@router.post(
    "/internal/policy/step-evaluate",
    response_model=StepPolicyEvaluateResponse,
)
def evaluate_step_policy(
    payload: StepPolicyEvaluateRequest,
    request: Request,
) -> StepPolicyEvaluateResponse:
    _require_service_token(request)
    tenant_id = payload.tenant_id.strip()
    actor_id = payload.actor_id.strip()
    correlation_id = payload.correlation_id.strip()
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tenant scope")
    if not actor_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid actor scope")
    if not correlation_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid correlation scope",
        )

    if payload.requires_human_approval or payload.risk_score >= 0.7:
        return StepPolicyEvaluateResponse(
            allow=False,
            outcome="pause",
            reasons=["human_approval_required"],
            required_approvals=["approver"],
            decision_artifact_id=f"artifact:{payload.run_id}:{payload.step_id}:pause",
        )
    if payload.risk_score >= 0.4:
        return StepPolicyEvaluateResponse(
            allow=False,
            outcome="deny",
            reasons=["risk_score_too_high_for_auto_execution"],
            required_approvals=[],
            decision_artifact_id=f"artifact:{payload.run_id}:{payload.step_id}:deny",
        )
    return StepPolicyEvaluateResponse(
        allow=True,
        outcome="allow",
        reasons=[],
        required_approvals=[],
        decision_artifact_id=f"artifact:{payload.run_id}:{payload.step_id}:allow",
    )
