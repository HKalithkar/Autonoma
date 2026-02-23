from __future__ import annotations

import difflib
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status

from libs.common.context import get_request_context
from libs.common.metrics import PLUGIN_REGISTRY

from .audit import audit_event
from .models import Approval, AuditEvent, EventIngest, Plugin, Workflow, WorkflowRun
from .policy import evaluate_policy
from .rbac import AuthContext
from .runner import resolve_secret_refs
from .runtime_cutover import launch_v1_run
from .workflow_inputs import (
    ensure_params_object,
    extract_schema_fields,
    validate_input_schema,
    validate_workflow_params,
)


class ToolExecutor:
    def __init__(
        self,
        session,
        ctx: AuthContext,
        llm_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._session = session
        self._ctx = ctx
        self._llm_overrides = llm_overrides or {}

    def _ensure(self, permission: str) -> None:
        required_prefix = f"{permission.split(':')[0]}:*"
        if permission not in self._ctx.permissions and required_prefix not in self._ctx.permissions:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    def _normalize_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return []

    def _resolve_workflow(
        self,
        workflow_id: str | None,
        workflow_name: str | None,
        *,
        allow_fuzzy_name: bool = False,
    ) -> Workflow:
        workflow: Workflow | None = None
        if workflow_id:
            try:
                workflow_uuid = uuid.UUID(workflow_id)
            except ValueError as exc:
                if not workflow_name:
                    workflow_name = workflow_id
                else:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workflow id"
                    ) from exc
            else:
                workflow = self._session.get(Workflow, workflow_uuid)
        if not workflow and workflow_name:
            workflow = (
                self._session.query(Workflow)
                .filter(Workflow.name == workflow_name)
                .order_by(Workflow.created_at.desc())
                .first()
            )
        if not workflow and workflow_name and allow_fuzzy_name:
            candidates = [item[0] for item in self._session.query(Workflow.name).all()]
            close = difflib.get_close_matches(workflow_name, candidates, n=1, cutoff=0.72)
            if close:
                workflow = (
                    self._session.query(Workflow)
                    .filter(Workflow.name == close[0])
                    .order_by(Workflow.created_at.desc())
                    .first()
                )
        if not workflow and not workflow_name and not workflow_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Missing workflow id"
            )
        if not workflow:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
        return workflow

    def workflow_list(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        self._ensure("workflow:read")
        workflows = (
            self._session.query(Workflow)
            .order_by(Workflow.created_at.desc())
            .limit(50)
            .all()
        )
        return [
            {
                "id": str(item.id),
                "name": item.name,
                "description": item.description,
                "plugin_id": str(item.plugin_id),
                "action": item.action,
                "input_schema": item.input_schema,
            }
            for item in workflows
        ]

    def workflow_create(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure("workflow:write")
        name = str(params.get("name", "")).strip()
        plugin_id = str(params.get("plugin_id", "")).strip()
        action = str(params.get("action", "")).strip()
        input_schema = params.get("input_schema")
        if not name or not plugin_id or not action:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing fields")
        if input_schema is not None and not isinstance(input_schema, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="input_schema must be an object"
            )
        if isinstance(input_schema, dict):
            validate_input_schema(input_schema)
        try:
            plugin_uuid = uuid.UUID(plugin_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid plugin id"
            ) from exc
        plugin = self._session.get(Plugin, plugin_uuid)
        if not plugin:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found")
        workflow = Workflow(
            name=name,
            description=params.get("description"),
            plugin_id=plugin.id,
            action=action,
            input_schema=input_schema,
            created_by=self._ctx.actor_id,
            tenant_id=self._ctx.tenant_id,
        )
        self._session.add(workflow)
        self._session.flush()
        audit_event(
            "workflow.register",
            "allow",
            {"workflow_id": str(workflow.id)},
            session=self._session,
        )
        return {"id": str(workflow.id), "name": workflow.name}

    def workflow_get(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure("workflow:read")
        workflow_id = str(params.get("workflow_id", "")).strip() or None
        workflow_name = (
            str(params.get("workflow_name") or params.get("name") or "").strip() or None
        )
        workflow = self._resolve_workflow(
            workflow_id,
            workflow_name,
            allow_fuzzy_name=True,
        )
        required_fields, optional_fields = extract_schema_fields(workflow.input_schema or {})
        return {
            "id": str(workflow.id),
            "name": workflow.name,
            "description": workflow.description,
            "plugin_id": str(workflow.plugin_id),
            "action": workflow.action,
            "input_schema": workflow.input_schema,
            "required_fields": required_fields,
            "optional_fields": optional_fields,
        }

    def workflow_delete(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure("workflow:write")
        workflow_id = str(params.get("workflow_id", "")).strip()
        try:
            workflow_uuid = uuid.UUID(workflow_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workflow id"
            ) from exc
        workflow = self._session.get(Workflow, workflow_uuid)
        if not workflow:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
        self._session.delete(workflow)
        audit_event("workflow.delete", "allow", {"workflow_id": workflow_id}, session=self._session)
        return {"status": "deleted", "workflow_id": workflow_id}

    def workflow_run(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure("workflow:run")
        workflow_id = str(params.get("workflow_id", "")).strip() or None
        workflow_name = (
            str(params.get("workflow_name") or params.get("name") or "").strip() or None
        )
        workflow = self._resolve_workflow(workflow_id, workflow_name)
        raw_environment = str(params.get("environment", "")).strip().lower()
        if not raw_environment:
            environment = "dev"
        elif raw_environment in {"prod", "production"}:
            environment = "prod"
        elif raw_environment in {"stage", "staging"}:
            environment = "stage"
        elif raw_environment == "dev":
            environment = "dev"
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid environment"
            )
        run_params = ensure_params_object(params.get("params"))
        if workflow.input_schema:
            validate_workflow_params(workflow.input_schema, run_params)
        decision = evaluate_policy(
            action="workflow:run",
            resource={"workflow_id": str(workflow.id)},
            parameters={"params": run_params, "environment": environment},
        )
        if not decision.allow and not decision.required_approvals:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"deny_reasons": decision.deny_reasons},
            )
        if decision.required_approvals:
            run = WorkflowRun(
                workflow_id=workflow.id,
                status="pending_approval",
                params=run_params,
                environment=environment,
                requested_by=self._ctx.actor_id,
                requested_by_name=self._ctx.username,
                tenant_id=self._ctx.tenant_id,
                gitops={
                    "adapter": "v1_runtime_pending",
                    "workflow_name": workflow.name,
                    "workflow_action": workflow.action,
                },
            )
            self._session.add(run)
            self._session.flush()
            approval = Approval(
                workflow_run_id=run.id,
                workflow_id=workflow.id,
                target_type="workflow",
                requested_by=self._ctx.actor_id,
                requested_by_name=self._ctx.username,
                required_role="approver",
                risk_level="high",
                rationale="Policy requires human approval.",
                plan_summary=f"Run workflow {workflow.name} ({workflow.action}).",
                artifacts={"deny_reasons": decision.deny_reasons},
                status="pending",
                correlation_id=get_request_context().correlation_id,
                tenant_id=self._ctx.tenant_id,
            )
            self._session.add(approval)
            self._session.flush()
            audit_event(
                "approval.requested",
                "allow",
                {
                    "workflow_id": workflow_id,
                    "workflow_run_id": str(run.id),
                    "approval_id": str(approval.id),
                },
                session=self._session,
            )
            return {
                "run_id": str(run.id),
                "status": "pending_approval",
                "approval_id": str(approval.id),
                "adapter": "v1_runtime",
            }
        plugin = self._session.get(Plugin, workflow.plugin_id)
        if not plugin:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found")
        context = get_request_context()
        resolved_params, redacted_params = resolve_secret_refs(
            self._session,
            run_params,
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
                "source": "v0_chat_workflow_run_migrated_to_v1",
                "workflow_id": str(workflow.id),
                "workflow_name": workflow.name,
                "workflow_action": workflow.action,
                "execution": {
                    "plugin": plugin.name,
                    "action": workflow.action,
                    "params": resolved_params,
                },
                "requires_human_approval": False,
                "risk_score": 0.1,
            },
            correlation_id=context.correlation_id,
            actor_id=self._ctx.actor_id,
            actor_name=self._ctx.username,
            tenant_id=self._ctx.tenant_id,
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
            params=redacted_params,
            environment=environment,
            requested_by=self._ctx.actor_id,
            requested_by_name=self._ctx.username,
            tenant_id=self._ctx.tenant_id,
            gitops={
                "adapter": "v1_runtime",
                "runtime_run_id": run_id_raw,
                "summary": str(launched.get("summary") or ""),
            },
        )
        self._session.add(run)
        self._session.flush()
        audit_event(
            "workflow.run.created",
            "allow",
            {
                "workflow_id": str(workflow.id),
                "workflow_run_id": str(run.id),
                "adapter": "v1_runtime",
            },
            session=self._session,
        )
        return {
            "run_id": str(run.id),
            "status": run.status,
            "summary": str(launched.get("summary") or ""),
            "adapter": "v1_runtime",
        }

    def agent_plan(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure("agent:run")
        goal = str(params.get("goal", "")).strip()
        if not goal:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing goal")
        environment = str(params.get("environment", "dev")).strip().lower()
        tools = self._normalize_list(params.get("tools")) or ["plugin_gateway.invoke"]
        documents = self._normalize_list(params.get("documents"))
        execute_tools = bool(params.get("execute_tools", False))
        launched = launch_v1_run(
            intent=goal,
            environment=environment,
            metadata={
                "source": "v0_chat_agent_plan_migrated_to_v1",
                "tools": tools,
                "documents": documents,
                "execute_tools": execute_tools,
            },
            correlation_id=get_request_context().correlation_id,
            actor_id=self._ctx.actor_id,
            actor_name=self._ctx.username,
            tenant_id=self._ctx.tenant_id,
        )
        run_id = str(launched.get("run_id"))
        payload = {
            "plan_id": f"v1-run-{run_id}",
            "status": "planned",
            "plan": [
                {
                    "step_id": "v1-run-launch",
                    "title": "Launch v1 run",
                    "description": "Legacy /v1/agent/plan adapted to v1 runs.",
                    "agent": "orchestrator",
                    "status": "planned",
                }
            ],
            "tool_calls": [],
            "memory_refs": [],
            "traces": [
                {
                    "event": "legacy.adapter.v1_run_launch",
                    "run_id": run_id,
                }
            ],
            "run_id": run_id,
            "summary": str(launched.get("summary") or ""),
        }
        audit_event(
            "agent.plan.created",
            "allow",
            {
                "plan_id": payload.get("plan_id"),
                "goal": goal,
                "environment": environment,
                "adapter": "v1",
                "run_id": run_id,
            },
            session=self._session,
        )
        return payload

    def plugin_list(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        self._ensure("plugin:read")
        plugins = self._session.query(Plugin).order_by(Plugin.created_at.desc()).limit(50).all()
        return [
            {
                "id": str(item.id),
                "name": item.name,
                "version": item.version,
                "plugin_type": item.plugin_type,
                "endpoint": item.endpoint,
                "actions": item.actions,
                "auth_type": item.auth_type,
                "auth_ref": item.auth_ref,
            }
            for item in plugins
        ]

    def plugin_get(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure("plugin:read")
        plugin_id = str(params.get("plugin_id", "")).strip()
        plugin_name = str(params.get("name", "")).strip()
        plugin: Plugin | None = None
        if plugin_id:
            try:
                plugin_uuid = uuid.UUID(plugin_id)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid plugin id"
                ) from exc
            plugin = self._session.get(Plugin, plugin_uuid)
        elif plugin_name:
            plugin = (
                self._session.query(Plugin)
                .filter(Plugin.name == plugin_name, Plugin.tenant_id == self._ctx.tenant_id)
                .first()
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Missing plugin id or name"
            )
        if not plugin:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found")
        return {
            "id": str(plugin.id),
            "name": plugin.name,
            "version": plugin.version,
            "plugin_type": plugin.plugin_type,
            "endpoint": plugin.endpoint,
            "actions": plugin.actions,
            "allowed_roles": plugin.allowed_roles,
            "auth_type": plugin.auth_type,
            "auth_ref": plugin.auth_ref,
        }

    def plugin_create(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure("plugin:write")
        name = str(params.get("name", "")).strip()
        endpoint = str(params.get("endpoint", "")).strip()
        if not name or not endpoint:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing fields")
        plugin = Plugin(
            name=name,
            version=params.get("version", "v1"),
            plugin_type=str(params.get("plugin_type", "workflow")),
            endpoint=endpoint,
            actions=params.get("actions", {}),
            allowed_roles=params.get("allowed_roles", {}),
            auth_type=str(params.get("auth_type", "none")),
            auth_ref=params.get("auth_ref"),
            auth_config=params.get("auth_config", {}),
            tenant_id=self._ctx.tenant_id,
        )
        self._session.add(plugin)
        self._session.flush()
        audit_event(
            "plugin.register",
            "allow",
            {"plugin_id": str(plugin.id)},
            session=self._session,
        )
        PLUGIN_REGISTRY.labels(action="register", plugin_type=plugin.plugin_type).inc()
        return {"id": str(plugin.id), "name": plugin.name}

    def plugin_delete(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure("plugin:write")
        plugin_id = str(params.get("plugin_id", "")).strip()
        try:
            plugin_uuid = uuid.UUID(plugin_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid plugin id"
            ) from exc
        plugin = self._session.get(Plugin, plugin_uuid)
        if not plugin:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found")
        self._session.delete(plugin)
        audit_event("plugin.delete", "allow", {"plugin_id": plugin_id}, session=self._session)
        PLUGIN_REGISTRY.labels(action="delete", plugin_type=plugin.plugin_type).inc()
        return {"status": "deleted", "plugin_id": plugin_id}

    def audit_list(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        self._ensure("audit:read")
        query = self._session.query(AuditEvent)
        source = str(params.get("source", "")).strip()
        event_type = str(params.get("event_type", "")).strip()
        actor_id = str(params.get("actor_id", "")).strip()
        outcome = str(params.get("outcome", "")).strip()
        if source:
            query = query.filter(AuditEvent.source.ilike(f"%{source}%"))
        if event_type:
            query = query.filter(AuditEvent.event_type.ilike(f"%{event_type}%"))
        if actor_id:
            query = query.filter(AuditEvent.actor_id.ilike(f"%{actor_id}%"))
        if outcome:
            query = query.filter(AuditEvent.outcome.ilike(f"%{outcome}%"))
        results = query.order_by(AuditEvent.created_at.desc()).limit(50).all()
        return [
            {
                "event_type": item.event_type,
                "outcome": item.outcome,
                "source": item.source,
                "actor_id": item.actor_id,
                "details": item.details,
                "created_at": item.created_at.isoformat(),
            }
            for item in results
        ]

    def approvals_list(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        self._ensure("approval:read")
        status_filter = params.get("status", "pending")
        query = self._session.query(Approval)
        if status_filter:
            query = query.filter(Approval.status == status_filter)
        approvals = query.order_by(Approval.created_at.desc()).limit(50).all()
        workflow_ids = {item.workflow_id for item in approvals if item.workflow_id}
        run_ids = {item.workflow_run_id for item in approvals if item.workflow_run_id}
        workflow_map: dict[uuid.UUID, Workflow] = {}
        run_map: dict[uuid.UUID, WorkflowRun] = {}
        if workflow_ids:
            workflow_query = self._session.query(Workflow).filter(Workflow.id.in_(workflow_ids))
            for workflow in workflow_query.all():
                workflow_map[workflow.id] = workflow
        if run_ids:
            for run in self._session.query(WorkflowRun).filter(WorkflowRun.id.in_(run_ids)).all():
                run_map[run.id] = run
        return [
            {
                "id": str(item.id),
                "status": item.status,
                "workflow_id": str(item.workflow_id) if item.workflow_id else None,
                "workflow_run_id": str(item.workflow_run_id) if item.workflow_run_id else None,
                "workflow_name": (
                    workflow_map[item.workflow_id].name
                    if item.workflow_id and item.workflow_id in workflow_map
                    else None
                ),
                "run_status": (
                    run_map[item.workflow_run_id].status
                    if item.workflow_run_id and item.workflow_run_id in run_map
                    else None
                ),
                "environment": (
                    run_map[item.workflow_run_id].environment
                    if item.workflow_run_id and item.workflow_run_id in run_map
                    else None
                ),
                "requested_by": item.requested_by,
                "requested_by_name": item.requested_by_name,
                "required_role": item.required_role,
                "risk_level": item.risk_level,
                "plan_summary": item.plan_summary,
                "rationale": item.rationale,
                "created_at": item.created_at.isoformat(),
                "correlation_id": item.correlation_id,
            }
            for item in approvals
        ]

    def runs_list(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        self._ensure("workflow:read")
        runs = (
            self._session.query(WorkflowRun)
            .order_by(WorkflowRun.created_at.desc())
            .limit(50)
            .all()
        )
        return [
            {
                "id": str(item.id),
                "workflow_id": str(item.workflow_id),
                "status": item.status,
                "job_id": item.job_id,
                "environment": item.environment,
                "created_at": item.created_at.isoformat(),
                "requested_by": item.requested_by,
                "requested_by_name": item.requested_by_name,
            }
            for item in runs
        ]

    def run_get(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure("workflow:read")
        run_id = str(params.get("run_id", "")).strip()
        try:
            run_uuid = uuid.UUID(run_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid run id"
            ) from exc
        run = self._session.get(WorkflowRun, run_uuid)
        if not run:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        workflow_name = None
        workflow = self._session.get(Workflow, run.workflow_id)
        if workflow:
            workflow_name = workflow.name
        approval = (
            self._session.query(Approval)
            .filter(Approval.workflow_run_id == run.id)
            .order_by(Approval.created_at.desc())
            .first()
        )
        return {
            "id": str(run.id),
            "workflow_id": str(run.workflow_id),
            "workflow_name": workflow_name,
            "status": run.status,
            "job_id": run.job_id,
            "environment": run.environment,
            "requested_by": run.requested_by,
            "requested_by_name": run.requested_by_name,
            "created_at": run.created_at.isoformat(),
            "approval_id": str(approval.id) if approval else None,
            "approval_status": approval.status if approval else None,
            "param_keys": list(run.params.keys()) if isinstance(run.params, dict) else [],
            "gitops": run.gitops or {},
        }

    def events_list(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        self._ensure("audit:read")
        query = self._session.query(EventIngest)
        if "since" in params:
            since = datetime.fromisoformat(params["since"])
            query = query.filter(EventIngest.received_at >= since)
        query = query.order_by(EventIngest.received_at.desc()).limit(50)
        return [
            {
                "event_type": item.event_type,
                "severity": item.severity,
                "summary": item.summary,
                "source": item.source,
                "environment": item.environment,
                "status": item.status,
                "received_at": item.received_at.isoformat(),
            }
            for item in query.all()
        ]

    def approval_get(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure("approval:read")
        approval_id = str(params.get("approval_id", "")).strip()
        try:
            approval_uuid = uuid.UUID(approval_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid approval id"
            ) from exc
        approval = self._session.get(Approval, approval_uuid)
        if not approval:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
        workflow_name = None
        run_status = None
        environment = None
        if approval.workflow_id:
            workflow = self._session.get(Workflow, approval.workflow_id)
            if workflow:
                workflow_name = workflow.name
        if approval.workflow_run_id:
            run = self._session.get(WorkflowRun, approval.workflow_run_id)
            if run:
                run_status = run.status
                environment = run.environment
        return {
            "id": str(approval.id),
            "status": approval.status,
            "workflow_id": str(approval.workflow_id) if approval.workflow_id else None,
            "workflow_run_id": str(approval.workflow_run_id) if approval.workflow_run_id else None,
            "workflow_name": workflow_name,
            "run_status": run_status,
            "environment": environment,
            "requested_by": approval.requested_by,
            "requested_by_name": approval.requested_by_name,
            "required_role": approval.required_role,
            "risk_level": approval.risk_level,
            "rationale": approval.rationale,
            "plan_summary": approval.plan_summary,
            "artifacts": approval.artifacts,
            "decision_comment": approval.decision_comment,
            "decided_by": approval.decided_by,
            "decided_by_name": approval.decided_by_name,
            "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
            "created_at": approval.created_at.isoformat(),
            "correlation_id": approval.correlation_id,
        }

    def approval_decision(self, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure("approval:write")
        approval_id = str(params.get("approval_id", "")).strip()
        decision = str(params.get("decision", "")).strip().lower()
        comment = params.get("comment")
        if decision not in {"approve", "reject"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid decision")
        try:
            approval_uuid = uuid.UUID(approval_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid approval id"
            ) from exc
        approval = self._session.get(Approval, approval_uuid)
        if not approval:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
        approval.status = "approved" if decision == "approve" else "rejected"
        approval.decided_by = self._ctx.actor_id
        approval.decided_by_name = self._ctx.username
        approval.decided_at = datetime.now(timezone.utc)
        approval.decision_comment = str(comment).strip() if comment else None

        run: WorkflowRun | None = None
        workflow_name = None
        if approval.workflow_run_id:
            run = self._session.get(WorkflowRun, approval.workflow_run_id)
            if not run:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found"
                )

        if decision == "approve" and run and approval.workflow_id:
            workflow = self._session.get(Workflow, approval.workflow_id)
            if not workflow:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found"
                )
            workflow_name = workflow.name
            plugin = self._session.get(Plugin, workflow.plugin_id)
            if not plugin:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found"
                )
            context = get_request_context()
            resolved_params, _ = resolve_secret_refs(
                self._session,
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
                    "source": "v0_chat_approval_decision_migrated_to_v1",
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
                actor_id=self._ctx.actor_id,
                actor_name=self._ctx.username,
                tenant_id=self._ctx.tenant_id,
            )
            run.status = str(launched.get("status") or "running")
            run.job_id = None
            gitops = run.gitops if isinstance(run.gitops, dict) else {}
            updated_gitops = dict(gitops)
            updated_gitops.update(
                {
                    "adapter": "v1_runtime",
                    "runtime_run_id": str(launched.get("run_id") or ""),
                    "summary": str(launched.get("summary") or ""),
                }
            )
            run.gitops = updated_gitops
        elif approval.workflow_id:
            workflow = self._session.get(Workflow, approval.workflow_id)
            if workflow:
                workflow_name = workflow.name

        self._session.flush()
        audit_event(
            "approval.decision",
            "allow",
            {
                "approval_id": approval_id,
                "decision": approval.status,
                "comment": approval.decision_comment,
            },
            session=self._session,
        )
        return {
            "approval_id": approval_id,
            "status": approval.status,
            "decision": decision,
            "workflow_run_id": str(approval.workflow_run_id)
            if approval.workflow_run_id
            else None,
            "run_status": run.status if run else None,
            "job_id": run.job_id if run else None,
            "workflow_name": workflow_name,
            "environment": run.environment if run else None,
        }
