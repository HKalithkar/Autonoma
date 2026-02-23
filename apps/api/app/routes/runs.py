from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from libs.common.context import get_request_context

from ..audit import audit_event
from ..db import session_scope
from ..models import Approval, RuntimeRun, Workflow, WorkflowRun
from ..rbac import require_permission
from ..runtime_store import RuntimeStore

router = APIRouter(prefix="/v1/runs", tags=["runs"])

_SENSITIVE_KEYS = {
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "access_key",
    "refresh_token",
    "credential",
    "credentials",
}

_TERMINAL_SUCCESS = {"succeeded", "success", "completed"}
_TERMINAL_FAILURE = {"failed", "error", "rejected", "aborted", "cancelled"}


class WorkflowRunStatusUpdate(BaseModel):
    run_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    job_id: str | None = None
    plugin: str | None = None
    tenant_id: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _require_service_token(request: Request) -> None:
    token = request.headers.get("x-service-token")
    expected = os.getenv("SERVICE_TOKEN")
    if not token or not expected or token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower()
    if normalized in _SENSITIVE_KEYS:
        return True
    return any(
        normalized.endswith(suffix)
        for suffix in (
            "_password",
            "_secret",
            "_token",
            "_api_key",
            "_apikey",
            "_private_key",
            "_access_key",
            "_refresh_token",
            "_credential",
            "_credentials",
        )
    )


def _redact_params(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, entry in value.items():
            key_str = str(key)
            if _is_sensitive_key(key_str):
                redacted[key_str] = "REDACTED"
            else:
                redacted[key_str] = _redact_params(entry)
        return redacted
    if isinstance(value, list):
        return [_redact_params(entry) for entry in value]
    return value


def _append_runtime_callback_event(
    *,
    session: Any,
    run_id: UUID,
    tenant_id: str,
    status_value: str,
    plugin: str | None,
    details: dict[str, Any],
    environment: str,
) -> None:
    store = RuntimeStore(session)
    occurred_at = _utcnow()
    event_type = "run.succeeded" if status_value in _TERMINAL_SUCCESS else "run.failed"
    event_id = f"{run_id}:external-status:{uuid.uuid4()}"
    actor_id = "service:workflow-adapter"
    correlation_id = str(run_id)
    payload = {
        "message": "External workflow status callback received.",
        "plugin": plugin,
        "status": status_value,
        "details": details,
    }
    envelope = {
        "event_id": event_id,
        "event_type": event_type,
        "schema_version": "v1",
        "run_id": str(run_id),
        "step_id": None,
        "timestamp": occurred_at.isoformat(),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "tenant_id": tenant_id,
        "agent_id": "workflow_status_callback",
        "payload": payload,
        "visibility_level": "tenant",
        "redaction": "none",
    }
    store.append_event(
        run_id=run_id,
        step_id=None,
        event_id=event_id,
        event_type=event_type,
        schema_version="v1",
        occurred_at=occurred_at,
        envelope=envelope,
        correlation_id=correlation_id,
        actor_id=actor_id,
        tenant_id=tenant_id,
        agent_id="workflow_status_callback",
        visibility_level="tenant",
        redaction="none",
    )
    store.append_event_ingest(
        event_type=event_type,
        severity="high" if status_value in _TERMINAL_FAILURE else "info",
        summary="Workflow run status updated from external callback.",
        source="api",
        details={
            "run_id": str(run_id),
            "status": status_value,
            "plugin": plugin,
            "callback_details": details,
        },
        environment=environment,
        status=status_value,
        actions={"source": "workflow_status_callback"},
        correlation_id=correlation_id,
        tenant_id=tenant_id,
        received_at=occurred_at,
    )


@router.post("/internal/status", status_code=status.HTTP_200_OK)
def update_workflow_run_status_internal(
    payload: WorkflowRunStatusUpdate,
    request: Request,
) -> dict[str, str]:
    _require_service_token(request)
    status_value = payload.status.strip().lower()
    if status_value not in (_TERMINAL_SUCCESS | _TERMINAL_FAILURE | {"running", "submitted"}):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status")
    try:
        run_uuid = UUID(payload.run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid run_id",
        ) from exc

    with session_scope() as session:
        run = (
            session.query(WorkflowRun)
            .filter(WorkflowRun.id == run_uuid, WorkflowRun.tenant_id == payload.tenant_id)
            .one_or_none()
        )
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow run not found",
            )
        run.status = status_value
        if payload.job_id:
            run.job_id = payload.job_id
        if isinstance(run.gitops, dict):
            run.gitops = {
                **run.gitops,
                "external_status": status_value,
                "external_plugin": payload.plugin,
            }
        else:
            run.gitops = {"external_status": status_value, "external_plugin": payload.plugin}

        runtime_run = (
            session.query(RuntimeRun)
            .filter(RuntimeRun.id == run_uuid, RuntimeRun.tenant_id == payload.tenant_id)
            .one_or_none()
        )
        if runtime_run is not None:
            runtime_run.status = status_value
            runtime_run.updated_at = _utcnow()

        if status_value in _TERMINAL_SUCCESS:
            audit_event(
                "workflow.run.completed",
                "allow",
                {
                    "workflow_run_id": str(run.id),
                    "status": status_value,
                    "plugin": payload.plugin,
                    "source": "workflow_status_callback",
                },
                session=session,
            )
            _append_runtime_callback_event(
                session=session,
                run_id=run_uuid,
                tenant_id=payload.tenant_id,
                status_value=status_value,
                plugin=payload.plugin,
                details=payload.details,
                environment=run.environment,
            )
        elif status_value in _TERMINAL_FAILURE:
            audit_event(
                "workflow.run.failed",
                "deny",
                {
                    "workflow_run_id": str(run.id),
                    "status": status_value,
                    "plugin": payload.plugin,
                    "source": "workflow_status_callback",
                },
                session=session,
            )
            _append_runtime_callback_event(
                session=session,
                run_id=run_uuid,
                tenant_id=payload.tenant_id,
                status_value=status_value,
                plugin=payload.plugin,
                details=payload.details,
                environment=run.environment,
            )
        session.flush()
    return {"status": "ok"}


def _orchestrator_url() -> str:
    return os.getenv("RUNTIME_ORCHESTRATOR_URL", "http://runtime-orchestrator:8003").rstrip("/")


def _orchestrator_headers() -> dict[str, str]:
    token = os.getenv("SERVICE_TOKEN")
    if not token:
        return {}
    return {"x-service-token": token}


def _runtime_run_id(run: WorkflowRun) -> str | None:
    if isinstance(run.gitops, dict):
        adapter = str(run.gitops.get("adapter") or "").strip()
        if adapter == "v1_runtime":
            runtime_id = str(run.gitops.get("runtime_run_id") or "").strip()
            if runtime_id:
                return runtime_id
    return str(run.id)


def _sync_v1_statuses(*, session, runs: list[WorkflowRun], tenant_id: str) -> None:
    if os.getenv("RUNTIME_V1_RUN_STATUS_SYNC_ENABLED", "false").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return
    headers = _orchestrator_headers()
    if not headers:
        return
    for run in runs:
        previous_status = str(run.status or "").strip().lower()
        runtime_id = _runtime_run_id(run)
        if not runtime_id:
            continue
        try:
            response = httpx.get(
                f"{_orchestrator_url()}/v1/orchestrator/runs/{runtime_id}",
                headers=headers,
                params={"tenant_id": tenant_id},
                timeout=0.5,
            )
        except httpx.HTTPError:
            continue
        if response.status_code != 200:
            continue
        data = response.json()
        status = str(data.get("status") or "").strip()
        if not status:
            continue
        run.status = status
        normalized = status.lower()
        if normalized == previous_status:
            continue
        if normalized in {"succeeded", "success", "completed"}:
            audit_event(
                "workflow.run.completed",
                "allow",
                {
                    "workflow_run_id": str(run.id),
                    "runtime_run_id": runtime_id,
                    "previous_status": previous_status or None,
                    "status": normalized,
                    "adapter": "v1_runtime",
                },
                session=session,
            )
        elif normalized in {"failed", "error", "rejected", "aborted", "cancelled"}:
            audit_event(
                "workflow.run.failed",
                "deny",
                {
                    "workflow_run_id": str(run.id),
                    "runtime_run_id": runtime_id,
                    "previous_status": previous_status or None,
                    "status": normalized,
                    "adapter": "v1_runtime",
                },
                session=session,
            )


@router.get("")
def list_runs(
    limit: int = 50,
    ctx=require_permission("workflow:read"),
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    with session_scope() as session:
        runs = (
            session.query(WorkflowRun, Workflow)
            .join(Workflow, WorkflowRun.workflow_id == Workflow.id)
            .order_by(WorkflowRun.created_at.desc())
            .limit(limit)
            .all()
        )
        _sync_v1_statuses(
            session=session,
            runs=[run for run, _ in runs],
            tenant_id=get_request_context().tenant_id,
        )
        session.flush()
        run_ids = [run.id for run, _ in runs]
        approvals: dict[UUID, Approval] = {}
        if run_ids:
            approval_rows = (
                session.query(Approval)
                .filter(Approval.workflow_run_id.in_(run_ids))
                .order_by(Approval.created_at.desc())
                .all()
            )
            for approval in approval_rows:
                if approval.workflow_run_id is None:
                    continue
                approvals.setdefault(approval.workflow_run_id, approval)
        results: list[dict[str, object]] = []
        for run, workflow in runs:
            approval_record: Approval | None = approvals.get(run.id)
            decided_at = approval_record.decided_at if approval_record else None
            results.append(
                {
                    "id": str(run.id),
                    "workflow_id": str(run.workflow_id),
                    "workflow_name": workflow.name,
                    "status": run.status,
                    "job_id": run.job_id,
                    "gitops": run.gitops,
                    "params": _redact_params(run.params),
                    "environment": run.environment,
                    "requested_by": run.requested_by,
                    "requested_by_name": run.requested_by_name,
                    "created_at": run.created_at.isoformat() if run.created_at else None,
                    "approval_id": str(approval_record.id) if approval_record else None,
                    "approval_status": approval_record.status if approval_record else None,
                    "approval_decided_by": (
                        approval_record.decided_by if approval_record else None
                    ),
                    "approval_decided_by_name": (
                        approval_record.decided_by_name if approval_record else None
                    ),
                    "approval_decided_at": decided_at.isoformat() if decided_at else None,
                }
            )
        return results
