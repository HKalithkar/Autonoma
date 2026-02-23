from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from libs.common.context import get_request_context
from libs.common.llm_config import validate_api_key_ref
from libs.common.llm_defaults import load_llm_defaults

from ..audit import audit_event
from ..db import session_scope
from ..models import AgentConfig, AgentEvaluation, AgentRun, RuntimeEvent, RuntimeRun
from ..policy import evaluate_policy
from ..rbac import require_permission
from ..runtime_cutover import launch_v1_run

router = APIRouter(prefix="/v1/agent", tags=["agent"])

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/configs")
def list_configs(ctx=require_permission("agent:config:read")) -> list[dict[str, Any]]:
    defaults = load_llm_defaults()
    with session_scope() as session:
        configs = {
            cfg.agent_type: cfg
            for cfg in session.query(AgentConfig).filter_by(tenant_id=ctx.tenant_id).all()
        }
        response: list[dict[str, Any]] = []
        for agent_type, default in defaults.items():
            cfg = configs.get(agent_type)
            if cfg:
                response.append(
                    {
                        "agent_type": agent_type,
                        "api_url": cfg.api_url,
                        "model": cfg.model,
                        "api_key_ref": cfg.api_key_ref,
                        "source": "override",
                    }
                )
            else:
                response.append(
                    {
                        "agent_type": agent_type,
                        "api_url": default.get("api_url"),
                        "model": default.get("model"),
                        "api_key_ref": default.get("api_key_ref"),
                        "source": "default",
                    }
                )
        return response


@router.put("/configs/{agent_type}")
def update_config(
    agent_type: str,
    payload: dict[str, Any],
    ctx=require_permission("agent:config:write"),
) -> dict[str, Any]:
    defaults = load_llm_defaults()
    if agent_type not in defaults:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown agent type")
    api_url = str(payload.get("api_url", "")).strip()
    model = str(payload.get("model", "")).strip()
    api_key_ref = str(payload.get("api_key_ref") or "").strip() or None
    if not api_url or not model:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing fields")
    try:
        validate_api_key_ref(api_key_ref)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid api_key_ref. Use env:VAR or secretkeyref:plugin:<name>:<path>.",
        ) from None
    with session_scope() as session:
        cfg = (
            session.query(AgentConfig)
            .filter_by(agent_type=agent_type, tenant_id=ctx.tenant_id)
            .one_or_none()
        )
        if cfg is None:
            cfg = AgentConfig(
                agent_type=agent_type,
                api_url=api_url,
                model=model,
                api_key_ref=api_key_ref,
                tenant_id=ctx.tenant_id,
            )
            session.add(cfg)
        else:
            cfg.api_url = api_url
            cfg.model = model
            cfg.api_key_ref = api_key_ref
            cfg.updated_at = _utcnow()
        session.flush()
        audit_event(
            "agent.config.update",
            "allow",
            {"agent_type": agent_type},
            session=session,
        )
        return {
            "agent_type": agent_type,
            "api_url": cfg.api_url,
            "model": cfg.model,
            "api_key_ref": cfg.api_key_ref,
            "source": "override",
        }


@router.post("/runs", status_code=status.HTTP_201_CREATED)
def create_run(
    payload: dict[str, Any],
    ctx=require_permission("agent:run"),
) -> dict[str, Any]:
    goal = str(payload.get("goal", "")).strip()
    environment = str(payload.get("environment", "")).strip().lower()
    if not goal:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing goal")
    if not environment:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing environment")
    if environment not in {"dev", "stage", "prod"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid environment")

    decision = evaluate_policy(
        action="agent:run",
        resource={"agent": "orchestrator"},
        parameters={"environment": environment, "goal": goal},
    )
    if not decision.allow and not decision.required_approvals:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"deny_reasons": decision.deny_reasons},
        )

    context = get_request_context()
    tools = list(payload.get("tools", []))
    documents = list(payload.get("documents", []))
    launched = launch_v1_run(
        intent=goal,
        environment=environment,
        metadata={
            "source": "v0_agent_runs_migrated_to_v1",
            "tools": tools,
            "documents": documents,
            "execute_tools": False,
        },
        correlation_id=context.correlation_id,
        actor_id=ctx.actor_id,
        actor_name=ctx.username,
        tenant_id=ctx.tenant_id,
    )
    run_id = str(launched.get("run_id"))
    with session_scope() as session:
        persisted_run_id: UUID | None = None
        try:
            persisted_run_id = UUID(run_id)
        except ValueError:
            persisted_run_id = None
        if persisted_run_id is not None:
            agent_run = session.get(AgentRun, persisted_run_id)
            if agent_run is None:
                session.add(
                    AgentRun(
                        id=persisted_run_id,
                        goal=goal,
                        environment=environment,
                        status=str(launched.get("status") or "planned"),
                        plan={
                            "adapter": "v1_runtime",
                            "summary": str(launched.get("summary") or ""),
                            "tools": tools,
                            "documents": documents,
                        },
                        requested_by=ctx.actor_id,
                        requested_by_name=ctx.username,
                        correlation_id=context.correlation_id,
                        tenant_id=ctx.tenant_id,
                    )
                )
            else:
                agent_run.status = str(launched.get("status") or agent_run.status or "planned")
                agent_run.requested_by = ctx.actor_id
                agent_run.requested_by_name = ctx.username
                agent_run.correlation_id = context.correlation_id
                agent_run.tenant_id = ctx.tenant_id
                plan = agent_run.plan if isinstance(agent_run.plan, dict) else {}
                plan.update(
                    {
                        "adapter": "v1_runtime",
                        "summary": str(launched.get("summary") or ""),
                        "tools": tools,
                        "documents": documents,
                    }
                )
                agent_run.plan = plan
        session.flush()
    audit_event(
        "agent.run.created",
        "allow",
        {
            "agent_run_id": run_id,
            "environment": environment,
            "adapter": "v1",
        },
    )
    return {
        "run_id": run_id,
        "status": "planned",
        "plan": {
            "plan_id": f"v1-run-{run_id}",
            "status": "planned",
            "plan": [],
            "tool_calls": [],
            "memory_refs": [],
            "traces": [
                {
                    "event": "legacy.adapter.v1_run_launch",
                    "run_id": run_id,
                }
            ],
        },
        "evaluation": {
            "score": 0.0,
            "verdict": "allow",
            "reasons": ["routed_to_v1"],
        },
        "approval_id": None,
        "memory_used": False,
        "adapter": "v1",
        "summary": str(launched.get("summary") or ""),
    }


@router.get("/runs")
def list_runs(ctx=require_permission("agent:run")) -> list[dict[str, Any]]:
    with session_scope() as session:
        runs = (
            session.query(AgentRun)
            .filter(AgentRun.tenant_id == ctx.tenant_id)
            .order_by(AgentRun.created_at.desc())
            .limit(200)
            .all()
        )
        runtime_status: dict[UUID, str] = {}
        runtime_timestamps: dict[UUID, datetime] = {}
        runtime_last_event: dict[UUID, str] = {}
        run_ids = [run.id for run in runs]
        if run_ids:
            runtime_runs = (
                session.query(RuntimeRun)
                .filter(RuntimeRun.id.in_(run_ids), RuntimeRun.tenant_id == ctx.tenant_id)
                .all()
            )
            runtime_status = {item.id: item.status for item in runtime_runs}
            runtime_timestamps = {item.id: item.updated_at for item in runtime_runs}

            runtime_events = (
                session.query(RuntimeEvent)
                .filter(RuntimeEvent.run_id.in_(run_ids), RuntimeEvent.tenant_id == ctx.tenant_id)
                .order_by(RuntimeEvent.occurred_at.desc())
                .all()
            )
            for event in runtime_events:
                runtime_last_event.setdefault(event.run_id, event.event_type)

        response: list[dict[str, Any]] = []
        for run in runs:
            evaluation = (
                session.query(AgentEvaluation)
                .filter(AgentEvaluation.agent_run_id == run.id)
                .order_by(AgentEvaluation.created_at.desc())
                .first()
            )
            derived_status = runtime_status.get(run.id, run.status)
            runtime_updated_at = runtime_timestamps.get(run.id)
            response.append(
                {
                    "id": str(run.id),
                    "goal": run.goal,
                    "environment": run.environment,
                    "status": derived_status,
                    "requested_by": run.requested_by,
                    "requested_by_name": run.requested_by_name,
                    "created_at": run.created_at.isoformat(),
                    "memory_used": _plan_used_memory(run.plan),
                    "runtime": {
                        "run_id": str(run.id),
                        "status": runtime_status.get(run.id),
                        "last_event_type": runtime_last_event.get(run.id),
                        "updated_at": (
                            runtime_updated_at.isoformat() if runtime_updated_at else None
                        ),
                    },
                    "evaluation": {
                        "score": evaluation.score,
                        "verdict": evaluation.verdict,
                        "reasons": evaluation.reasons.get("items", []),
                    }
                    if evaluation
                    else None,
                }
            )
        return response


def _plan_used_memory(plan: dict[str, Any]) -> bool:
    traces = plan.get("traces") or []
    for trace in traces:
        if trace.get("event") == "memory.vector.search":
            return True
    return False
