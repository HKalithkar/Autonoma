from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status

from libs.common.context import get_request_context
from libs.common.metrics import APPROVALS, WORKFLOW_REGISTRY, WORKFLOW_RUNS, WORKFLOWS_TOTAL

from ..audit import audit_event
from ..db import session_scope
from ..models import Approval, Plugin, Workflow, WorkflowRun
from ..policy import evaluate_policy
from ..rbac import require_permission
from ..runner import resolve_secret_refs
from ..runtime_cutover import launch_v1_run
from ..workflow_inputs import ensure_params_object, validate_input_schema, validate_workflow_params

router = APIRouter(prefix="/v1/workflows", tags=["workflows"])


def _required_role(required_approvals: list[str]) -> str:
    if "human_approval" in required_approvals:
        return "approver"
    return "approver"


@router.get("")
def list_workflows(ctx=require_permission("workflow:read")) -> list[dict[str, Any]]:
    with session_scope() as session:
        workflows = session.query(Workflow).all()
        WORKFLOWS_TOTAL.labels(tenant_id=ctx.tenant_id).set(len(workflows))
        return [
            {
                "id": str(flow.id),
                "name": flow.name,
                "description": flow.description,
                "action": flow.action,
                "plugin_id": str(flow.plugin_id),
                "input_schema": flow.input_schema,
            }
            for flow in workflows
        ]


@router.post("", status_code=status.HTTP_201_CREATED)
def register_workflow(
    payload: dict[str, Any],
    ctx=require_permission("workflow:write"),
) -> dict[str, Any]:
    name = str(payload.get("name", "")).strip()
    plugin_id = payload.get("plugin_id")
    action = str(payload.get("action", "")).strip()
    input_schema = payload.get("input_schema")
    if not name or not plugin_id or not action:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing fields")
    if input_schema is not None and not isinstance(input_schema, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="input_schema must be an object"
        )
    if isinstance(input_schema, dict):
        validate_input_schema(input_schema)
    try:
        plugin_uuid = uuid.UUID(str(plugin_id))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid plugin id",
        ) from exc
    with session_scope() as session:
        plugin = session.get(Plugin, plugin_uuid)
        if not plugin:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found")
        workflow = Workflow(
            name=name,
            description=payload.get("description"),
            plugin_id=plugin.id,
            action=action,
            input_schema=input_schema,
            created_by=ctx.actor_id,
            tenant_id=ctx.tenant_id,
        )
        session.add(workflow)
        session.flush()
        audit_event(
            "workflow.register", "allow", {"workflow_id": str(workflow.id)}, session=session
        )
        WORKFLOW_REGISTRY.labels(action="register").inc()
    return {"id": str(workflow.id), "name": workflow.name}


@router.delete("/{workflow_id}", status_code=status.HTTP_200_OK)
def delete_workflow(
    workflow_id: str,
    ctx=require_permission("workflow:write"),
) -> dict[str, Any]:
    try:
        workflow_uuid = uuid.UUID(workflow_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid workflow id",
        ) from exc
    with session_scope() as session:
        workflow = session.get(Workflow, workflow_uuid)
        if not workflow:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

        run_ids = [
            run_id
            for (run_id,) in session.query(WorkflowRun.id)
            .filter(WorkflowRun.workflow_id == workflow.id)
            .all()
        ]
        if run_ids:
            session.query(Approval).filter(Approval.workflow_run_id.in_(run_ids)).delete(
                synchronize_session=False
            )
            session.query(WorkflowRun).filter(WorkflowRun.id.in_(run_ids)).delete(
                synchronize_session=False
            )

        session.delete(workflow)
        audit_event("workflow.delete", "allow", {"workflow_id": str(workflow.id)}, session=session)
        WORKFLOW_REGISTRY.labels(action="delete").inc()
        session.flush()
        return {"status": "deleted", "workflow_id": str(workflow.id)}


@router.post("/{workflow_id}/runs", status_code=status.HTTP_202_ACCEPTED)
def trigger_run(
    workflow_id: str,
    payload: dict[str, Any],
    ctx=require_permission("workflow:run"),
) -> dict[str, Any]:
    try:
        workflow_uuid = uuid.UUID(workflow_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid workflow id",
        ) from exc
    params = ensure_params_object(payload.get("params"))
    environment = str(payload.get("environment", "")).strip().lower()
    if not environment:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing environment")
    if environment not in {"dev", "stage", "prod"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid environment")
    with session_scope() as session:
        workflow = session.get(Workflow, workflow_uuid)
        if not workflow:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
        plugin = session.get(Plugin, workflow.plugin_id)
        if not plugin:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found")
        if workflow.input_schema:
            validate_workflow_params(workflow.input_schema, params)

        decision = evaluate_policy(
            action="workflow:run",
            resource={"workflow_id": workflow_id},
            parameters={"params": params, "environment": environment},
        )
        if not decision.allow and not decision.required_approvals:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "deny_reasons": decision.deny_reasons,
                    "required_approvals": decision.required_approvals,
                },
            )
        context = get_request_context()
        if decision.required_approvals:
            run = WorkflowRun(
                workflow_id=workflow.id,
                status="pending_approval",
                requested_by=ctx.actor_id,
                requested_by_name=ctx.username,
                tenant_id=ctx.tenant_id,
                params=params,
                environment=environment,
                gitops={
                    "adapter": "v1_runtime_pending",
                    "workflow_name": workflow.name,
                    "workflow_action": workflow.action,
                },
            )
            session.add(run)
            session.flush()
            approval = Approval(
                workflow_run_id=run.id,
                workflow_id=workflow.id,
                target_type="workflow",
                requested_by=ctx.actor_id,
                requested_by_name=ctx.username,
                required_role=_required_role(decision.required_approvals),
                risk_level="high" if "human_approval" in decision.required_approvals else "medium",
                rationale="Policy requires human approval.",
                plan_summary=f"Run workflow {workflow.name} ({workflow.action}).",
                artifacts={"deny_reasons": decision.deny_reasons},
                status="pending",
                correlation_id=context.correlation_id,
                tenant_id=ctx.tenant_id,
            )
            session.add(approval)
            WORKFLOW_RUNS.labels(status=run.status, environment=environment).inc()
            APPROVALS.labels(status="requested", target_type="workflow").inc()
            audit_event(
                "approval.requested",
                "allow",
                {
                    "workflow_id": workflow_id,
                    "workflow_run_id": str(run.id),
                    "approval_id": str(approval.id),
                    "required_role": approval.required_role,
                    "adapter": "v1_runtime",
                },
                session=session,
            )
            session.flush()
            return {
                "run_id": str(run.id),
                "status": run.status,
                "required_approvals": decision.required_approvals,
                "approval_id": str(approval.id),
                "adapter": "v1_runtime",
            }

        resolved_params, redacted_params = resolve_secret_refs(
            session,
            params,
            context={
                "correlation_id": context.correlation_id,
                "actor_id": context.actor_id,
                "tenant_id": context.tenant_id,
            },
        )
        launched = launch_v1_run(
            intent=f"Run workflow {workflow.name} ({workflow.action})",
            environment=environment,
            metadata={
                "source": "v0_workflow_run_migrated_to_v1",
                "workflow_id": str(workflow.id),
                "workflow_name": workflow.name,
                "workflow_action": workflow.action,
                "execution": {
                    "plugin": plugin.name,
                    "action": workflow.action,
                    "params": resolved_params,
                },
                "requires_human_approval": bool(decision.required_approvals),
                "risk_score": 0.8 if decision.required_approvals else 0.1,
            },
            correlation_id=context.correlation_id,
            actor_id=ctx.actor_id,
            actor_name=ctx.username,
            tenant_id=ctx.tenant_id,
        )
        run_id_raw = str(launched.get("run_id", "")).strip()
        try:
            run_uuid = uuid.UUID(run_id_raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Invalid orchestrator run_id",
            ) from exc
        run = WorkflowRun(
            id=run_uuid,
            workflow_id=workflow.id,
            status=str(launched.get("status") or "running"),
            requested_by=ctx.actor_id,
            requested_by_name=ctx.username,
            tenant_id=ctx.tenant_id,
            params=redacted_params,
            environment=environment,
            gitops={
                "adapter": "v1_runtime",
                "runtime_run_id": run_id_raw,
                "summary": str(launched.get("summary") or ""),
            },
        )
        session.add(run)
        WORKFLOW_RUNS.labels(status=run.status, environment=environment).inc()
        audit_event(
            "workflow.run.created",
            "allow",
            {
                "workflow_id": str(workflow.id),
                "workflow_run_id": str(run.id),
                "adapter": "v1_runtime",
                "required_approvals": decision.required_approvals,
            },
            session=session,
        )
        session.flush()
        response: dict[str, Any] = {
            "run_id": str(run.id),
            "status": run.status,
            "summary": str(launched.get("summary") or ""),
            "adapter": "v1_runtime",
        }
        if decision.required_approvals:
            response["required_approvals"] = decision.required_approvals
        return response
