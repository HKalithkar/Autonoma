from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from libs.common.context import set_request_context
from libs.common.metrics import WORKFLOW_RUNS

from ..audit import audit_event
from ..db import session_scope
from ..models import PluginInvocation, WorkflowRun

router = APIRouter(prefix="/v1/gitops", tags=["gitops"])


class GitOpsWebhook(BaseModel):
    workflow_run_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    commit_sha: str | None = None
    pr_url: str | None = None
    pipeline_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


def _require_service_token(request: Request) -> None:
    token = request.headers.get("x-service-token")
    expected = os.getenv("SERVICE_TOKEN")
    if not token or not expected or token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


@router.post("/webhook")
def gitops_webhook(payload: GitOpsWebhook, request: Request) -> dict[str, Any]:
    _require_service_token(request)
    try:
        run_id = uuid.UUID(payload.workflow_run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid run id"
        ) from exc
    with session_scope() as session:
        run = session.query(WorkflowRun).filter_by(id=run_id).one_or_none()
        if not run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found"
            )
        set_request_context(
            correlation_id=str(run.id),
            actor_id="service:gitops",
            tenant_id=run.tenant_id,
        )
        run.gitops = {
            "status": payload.status,
            "commit_sha": payload.commit_sha,
            "pr_url": payload.pr_url,
            "pipeline_id": payload.pipeline_id,
            "details": payload.details,
        }
        run.status = payload.status
        WORKFLOW_RUNS.labels(status=run.status, environment=run.environment).inc()
        if payload.status.lower() in {"failed", "error"}:
            _ingest_failure_memory(
                run_id=str(run.id),
                tenant_id=run.tenant_id,
                status=payload.status,
                details=payload.details,
            )
        invocation = None
        if run.job_id:
            candidates = (
                session.query(PluginInvocation)
                .filter(PluginInvocation.action == "create_change")
                .order_by(PluginInvocation.created_at.desc())
                .all()
            )
            for candidate in candidates:
                if candidate.result.get("job_id") == run.job_id:
                    invocation = candidate
                    break
        if invocation:
            invocation.webhook_status = payload.status
            invocation.webhook_received_at = datetime.now(timezone.utc)
        audit_event(
            "gitops.webhook",
            "allow",
            {
                "workflow_run_id": payload.workflow_run_id,
                "status": payload.status,
                "commit_sha": payload.commit_sha,
                "pipeline_id": payload.pipeline_id,
            },
            session=session,
        )
        session.flush()
    return {"status": "ok"}


def _ingest_failure_memory(
    *,
    run_id: str,
    tenant_id: str,
    status: str,
    details: dict[str, Any],
) -> None:
    token = os.getenv("SERVICE_TOKEN")
    if not token:
        return
    payload = {
        "texts": [
            f"gitops failure for run {run_id}: {status}",
            f"details: {details}",
        ],
        "metadata": {
            "type": "failure",
            "source": "gitops",
            "workflow_run_id": run_id,
        },
        "context": {
            "correlation_id": run_id,
            "actor_id": "service:gitops",
            "tenant_id": tenant_id,
        },
    }
    try:
        httpx.post(
            "http://agent-runtime:8001/v1/memory/ingest",
            headers={"x-service-token": token},
            json=payload,
            timeout=5.0,
        ).raise_for_status()
        audit_event(
            "memory.ingest",
            "allow",
            {"workflow_run_id": run_id, "type": "failure"},
        )
    except httpx.RequestError:
        audit_event(
            "memory.ingest",
            "deny",
            {"workflow_run_id": run_id, "reason": "agent_runtime_unavailable"},
        )
