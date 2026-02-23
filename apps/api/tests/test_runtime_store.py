from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from apps.api.app.db import init_db, reset_db_cache, session_scope
from apps.api.app.runtime_store import RuntimeStore


def _configure_db(tmp_path: Path) -> None:
    db_path = tmp_path / "test_runtime_store.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["DB_AUTO_CREATE"] = "true"
    os.environ["DB_SEED"] = "false"
    reset_db_cache()
    init_db()


def test_runtime_store_run_is_tenant_scoped(tmp_path: Path) -> None:
    _configure_db(tmp_path)
    with session_scope() as session:
        store = RuntimeStore(session)
        run = store.create_run(
            intent="Deploy workflow",
            environment="dev",
            requester_actor_id="user-1",
            requester_actor_name="Ops User",
            tenant_id="tenant-a",
            correlation_id="corr-1",
            metadata={"source": "unit"},
        )

    with session_scope() as session:
        store = RuntimeStore(session)
        found = store.get_run(run_id=run.id, tenant_id="tenant-a")
        missing = store.get_run(run_id=run.id, tenant_id="tenant-b")
        assert found is not None
        assert found.intent == "Deploy workflow"
        assert missing is None


def test_runtime_store_persists_steps_and_events(tmp_path: Path) -> None:
    _configure_db(tmp_path)
    with session_scope() as session:
        store = RuntimeStore(session)
        run = store.create_run(
            intent="Deploy workflow",
            environment="dev",
            requester_actor_id="user-1",
            tenant_id="tenant-a",
            correlation_id="corr-2",
        )
        step = store.create_step(
            run_id=run.id,
            step_key="step-policy",
            assigned_agent="security_guardian_worker",
            tenant_id="tenant-a",
            correlation_id="corr-2",
        )
        store.append_event(
            run_id=run.id,
            step_id=step.id,
            event_id="evt-1",
            event_type="policy.decision.recorded",
            schema_version="v1",
            occurred_at=datetime.now(timezone.utc),
            envelope={"payload": {"allow": True}},
            correlation_id="corr-2",
            actor_id="svc-orchestrator",
            tenant_id="tenant-a",
            agent_id="security_guardian_worker",
        )

    with session_scope() as session:
        store = RuntimeStore(session)
        events = store.list_events(run_id=run.id, tenant_id="tenant-a")
        assert len(events) == 1
        assert events[0].event_type == "policy.decision.recorded"
        assert events[0].envelope["agent_id"] == "security_guardian_worker"


def test_runtime_store_tool_invocation_is_idempotent_per_tenant(tmp_path: Path) -> None:
    _configure_db(tmp_path)
    with session_scope() as session:
        store = RuntimeStore(session)
        run = store.create_run(
            intent="Deploy workflow",
            environment="dev",
            requester_actor_id="user-1",
            tenant_id="tenant-a",
            correlation_id="corr-3",
        )
        step = store.create_step(
            run_id=run.id,
            step_key="step-tool",
            assigned_agent="event_response_worker",
            tenant_id="tenant-a",
            correlation_id="corr-3",
        )

        first = store.record_tool_invocation(
            run_id=run.id,
            step_id=step.id,
            tool_name="plugin_gateway",
            action="invoke",
            idempotency_key="idem-1",
            status="started",
            request_payload={"x": 1},
            response_payload={},
            correlation_id="corr-3",
            actor_id="svc-orchestrator",
            tenant_id="tenant-a",
        )
        second = store.record_tool_invocation(
            run_id=run.id,
            step_id=step.id,
            tool_name="plugin_gateway",
            action="invoke",
            idempotency_key="idem-1",
            status="succeeded",
            request_payload={"x": 1},
            response_payload={"ok": True},
            correlation_id="corr-3",
            actor_id="svc-orchestrator",
            tenant_id="tenant-a",
        )
        third = store.record_tool_invocation(
            run_id=run.id,
            step_id=step.id,
            tool_name="plugin_gateway",
            action="invoke",
            idempotency_key="idem-1",
            status="started",
            request_payload={"x": 1},
            response_payload={},
            correlation_id="corr-3",
            actor_id="svc-orchestrator",
            tenant_id="tenant-b",
        )

        assert first.id == second.id
        assert third.id != first.id


def test_runtime_store_updates_tool_invocation(tmp_path: Path) -> None:
    _configure_db(tmp_path)
    with session_scope() as session:
        store = RuntimeStore(session)
        run = store.create_run(
            intent="Deploy workflow",
            environment="dev",
            requester_actor_id="user-1",
            tenant_id="tenant-a",
            correlation_id="corr-4",
        )
        step = store.create_step(
            run_id=run.id,
            step_key="step-tool-update",
            assigned_agent="event_response_worker",
            tenant_id="tenant-a",
            correlation_id="corr-4",
        )
        invocation = store.record_tool_invocation(
            run_id=run.id,
            step_id=step.id,
            tool_name="plugin_gateway",
            action="invoke",
            idempotency_key="idem-update-1",
            status="started",
            request_payload={"x": 1},
            response_payload={},
            correlation_id="corr-4",
            actor_id="svc-orchestrator",
            tenant_id="tenant-a",
        )
        updated = store.update_tool_invocation(
            invocation=invocation,
            status="completed",
            retry_count=1,
            normalized_outcome="success",
            response_payload={"job_id": "abc"},
        )
        fetched = store.get_tool_invocation(
            tenant_id="tenant-a",
            idempotency_key="idem-update-1",
        )

        assert updated.status == "completed"
        assert fetched is not None
        assert fetched.normalized_outcome == "success"
