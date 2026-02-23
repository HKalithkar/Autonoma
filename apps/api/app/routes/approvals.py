from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status

from libs.common.context import get_request_context
from libs.common.metrics import APPROVALS, WORKFLOW_RUNS

from ..audit import audit_event
from ..db import session_scope
from ..models import AgentRun, Approval, Plugin, Workflow, WorkflowRun
from ..rbac import require_permission
from ..runner import resolve_secret_refs
from ..runtime_cutover import launch_v1_run

router = APIRouter(prefix="/v1/approvals", tags=["approvals"])


@router.get("")
def list_approvals(
    status_filter: str | None = "pending",
    ctx=require_permission("approval:read"),
) -> list[dict[str, Any]]:
    with session_scope() as session:
        query = (
            session.query(Approval, Workflow, AgentRun)
            .outerjoin(Workflow, Approval.workflow_id == Workflow.id)
            .outerjoin(AgentRun, Approval.agent_run_id == AgentRun.id)
        )
        if status_filter:
            query = query.filter(Approval.status == status_filter)
        approvals = query.all()
        return [
            {
                "id": str(approval.id),
                "workflow_id": str(approval.workflow_id) if approval.workflow_id else None,
                "workflow_run_id": str(approval.workflow_run_id)
                if approval.workflow_run_id
                else None,
                "agent_run_id": str(approval.agent_run_id) if approval.agent_run_id else None,
                "target_type": approval.target_type,
                "target_name": workflow.name
                if workflow
                else (agent_run.goal if agent_run else "Agent run"),
                "requested_by": approval.requested_by,
                "requested_by_name": approval.requested_by_name,
                "required_role": approval.required_role,
                "risk_level": approval.risk_level,
                "rationale": approval.rationale,
                "plan_summary": approval.plan_summary,
                "status": approval.status,
                "decision_comment": approval.decision_comment,
                "decided_by": approval.decided_by,
                "decided_by_name": approval.decided_by_name,
                "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
                "created_at": approval.created_at.isoformat(),
            }
            for approval, workflow, agent_run in approvals
        ]


@router.post("/{approval_id}/decision")
def decide_approval(
    approval_id: str,
    payload: dict[str, Any],
    ctx=require_permission("approval:write"),
) -> dict[str, Any]:
    decision = str(payload.get("decision", "")).strip().lower()
    if decision not in {"approve", "reject"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid decision")

    with session_scope() as session:
        try:
            approval_uuid = uuid.UUID(approval_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid approval id",
            ) from exc
        approval = session.get(Approval, approval_uuid)
        if not approval:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
        if approval.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Approval already decided"
            )
        if approval.requested_by == ctx.actor_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Requester cannot approve their own request",
            )

        approval.status = "approved" if decision == "approve" else "rejected"
        approval.decision_comment = payload.get("comment")
        approval.decided_by = ctx.actor_id
        approval.decided_by_name = ctx.username
        approval.decided_at = datetime.now(timezone.utc)

        agent_run_status: str | None = None
        run: WorkflowRun | None = None
        if approval.target_type == "agent_run":
            agent_run = session.get(AgentRun, approval.agent_run_id)
            if not agent_run:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found"
                )
            agent_run.status = "approved" if decision == "approve" else "rejected"
            agent_run_status = agent_run.status
        else:
            run = session.get(WorkflowRun, approval.workflow_run_id)
            if not run:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found"
                )

            if decision == "approve":
                workflow = session.get(Workflow, approval.workflow_id)
                if not workflow:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found"
                    )
                gitops = run.gitops if isinstance(run.gitops, dict) else {}
                plugin = session.get(Plugin, workflow.plugin_id)
                if not plugin:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Plugin not found",
                    )
                context = get_request_context()
                resolved_params, _ = resolve_secret_refs(
                    session,
                    run.params or {},
                    context={
                        "correlation_id": context.correlation_id,
                        "actor_id": context.actor_id,
                        "tenant_id": context.tenant_id,
                    },
                )
                launched = launch_v1_run(
                    intent=f"Run workflow {workflow.name} ({workflow.action})",
                    environment=run.environment,
                    metadata={
                        "source": "v0_approval_decision_migrated_to_v1",
                        "workflow_id": str(workflow.id),
                        "workflow_name": workflow.name,
                        "workflow_action": workflow.action,
                        "approval_id": str(approval.id),
                        "execution": {
                            "plugin": plugin.name,
                            "action": workflow.action,
                            "params": resolved_params,
                        },
                    },
                    correlation_id=context.correlation_id,
                    actor_id=context.actor_id,
                    actor_name=ctx.username,
                    tenant_id=ctx.tenant_id,
                )
                run.status = str(launched.get("status") or "running")
                updated_gitops = dict(gitops)
                updated_gitops.update(
                    {
                        "adapter": "v1_runtime",
                        "runtime_run_id": str(launched.get("run_id") or ""),
                        "summary": str(launched.get("summary") or ""),
                    }
                )
                run.gitops = updated_gitops
                run.job_id = None
                WORKFLOW_RUNS.labels(status=run.status, environment=run.environment).inc()
            else:
                run.status = "rejected"
                WORKFLOW_RUNS.labels(status=run.status, environment=run.environment).inc()

        audit_event(
            "approval.decision",
            "allow" if decision == "approve" else "deny",
            {
                "approval_id": str(approval.id),
                "target_type": approval.target_type,
                "workflow_run_id": str(run.id) if run else None,
                "agent_run_id": str(approval.agent_run_id) if approval.agent_run_id else None,
                "decision": decision,
                "comment": approval.decision_comment,
                "correlation_id": get_request_context().correlation_id,
            },
            session=session,
        )
        APPROVALS.labels(
            status="approved" if decision == "approve" else "rejected",
            target_type=approval.target_type,
        ).inc()
        session.flush()
        return {
            "approval_id": str(approval.id),
            "status": approval.status,
            "run_id": str(run.id) if run else None,
            "run_status": run.status if run else None,
            "job_id": run.job_id if run else None,
            "agent_run_id": str(approval.agent_run_id) if approval.agent_run_id else None,
            "agent_run_status": agent_run_status,
        }
