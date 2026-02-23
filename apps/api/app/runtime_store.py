from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from .models import EventIngest, RuntimeEvent, RuntimeRun, RuntimeStep, RuntimeToolInvocation


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RuntimeStore:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_run(
        self,
        *,
        intent: str,
        environment: str,
        requester_actor_id: str,
        tenant_id: str,
        correlation_id: str,
        metadata: dict[str, Any] | None = None,
        requester_actor_name: str | None = None,
    ) -> RuntimeRun:
        run = RuntimeRun(
            intent=intent,
            environment=environment,
            requester_actor_id=requester_actor_id,
            requester_actor_name=requester_actor_name,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            run_metadata=metadata or {},
        )
        self._session.add(run)
        self._session.flush()
        return run

    def get_run(self, *, run_id: UUID, tenant_id: str) -> RuntimeRun | None:
        return (
            self._session.query(RuntimeRun)
            .filter(RuntimeRun.id == run_id, RuntimeRun.tenant_id == tenant_id)
            .one_or_none()
        )

    def create_step(
        self,
        *,
        run_id: UUID,
        step_key: str,
        assigned_agent: str,
        tenant_id: str,
        correlation_id: str,
    ) -> RuntimeStep:
        step = RuntimeStep(
            run_id=run_id,
            step_key=step_key,
            assigned_agent=assigned_agent,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
        )
        self._session.add(step)
        self._session.flush()
        return step

    def append_event(
        self,
        *,
        run_id: UUID,
        step_id: UUID | None,
        event_id: str,
        event_type: str,
        schema_version: str,
        occurred_at: datetime,
        envelope: dict[str, Any],
        correlation_id: str,
        actor_id: str,
        tenant_id: str,
        agent_id: str,
        visibility_level: str = "tenant",
        redaction: str = "none",
    ) -> RuntimeEvent:
        event_payload = dict(envelope)
        event_payload.setdefault("agent_id", agent_id)
        event = RuntimeEvent(
            run_id=run_id,
            step_id=step_id,
            event_id=event_id,
            event_type=event_type,
            schema_version=schema_version,
            occurred_at=occurred_at,
            envelope=event_payload,
            correlation_id=correlation_id,
            actor_id=actor_id,
            tenant_id=tenant_id,
            visibility_level=visibility_level,
            redaction=redaction,
        )
        self._session.add(event)
        self._session.flush()
        return event

    def append_event_ingest(
        self,
        *,
        event_type: str,
        severity: str,
        summary: str,
        source: str,
        details: dict[str, Any],
        environment: str,
        status: str,
        actions: dict[str, Any],
        correlation_id: str,
        tenant_id: str,
        received_at: datetime,
    ) -> EventIngest:
        ingest = EventIngest(
            event_type=event_type,
            severity=severity,
            summary=summary,
            source=source,
            details=details,
            environment=environment,
            status=status,
            actions=actions,
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            received_at=received_at,
        )
        self._session.add(ingest)
        self._session.flush()
        return ingest

    def list_events(self, *, run_id: UUID, tenant_id: str) -> list[RuntimeEvent]:
        return (
            self._session.query(RuntimeEvent)
            .filter(RuntimeEvent.run_id == run_id, RuntimeEvent.tenant_id == tenant_id)
            .order_by(RuntimeEvent.created_at.asc())
            .all()
        )

    def record_tool_invocation(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        tool_name: str,
        action: str,
        idempotency_key: str,
        status: str,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any],
        correlation_id: str,
        actor_id: str,
        tenant_id: str,
        retry_count: int = 0,
        normalized_outcome: str | None = None,
    ) -> RuntimeToolInvocation:
        existing = (
            self._session.query(RuntimeToolInvocation)
            .filter(
                RuntimeToolInvocation.tenant_id == tenant_id,
                RuntimeToolInvocation.idempotency_key == idempotency_key,
            )
            .one_or_none()
        )
        if existing is not None:
            return existing

        invocation = RuntimeToolInvocation(
            run_id=run_id,
            step_id=step_id,
            tool_name=tool_name,
            action=action,
            status=status,
            idempotency_key=idempotency_key,
            retry_count=retry_count,
            normalized_outcome=normalized_outcome,
            request_payload=request_payload,
            response_payload=response_payload,
            correlation_id=correlation_id,
            actor_id=actor_id,
            tenant_id=tenant_id,
            updated_at=_utcnow(),
        )
        self._session.add(invocation)
        self._session.flush()
        return invocation

    def get_tool_invocation(
        self,
        *,
        tenant_id: str,
        idempotency_key: str,
    ) -> RuntimeToolInvocation | None:
        return (
            self._session.query(RuntimeToolInvocation)
            .filter(
                RuntimeToolInvocation.tenant_id == tenant_id,
                RuntimeToolInvocation.idempotency_key == idempotency_key,
            )
            .one_or_none()
        )

    def update_tool_invocation(
        self,
        *,
        invocation: RuntimeToolInvocation,
        status: str,
        retry_count: int,
        normalized_outcome: str | None,
        response_payload: dict[str, Any],
    ) -> RuntimeToolInvocation:
        invocation.status = status
        invocation.retry_count = retry_count
        invocation.normalized_outcome = normalized_outcome
        invocation.response_payload = response_payload
        invocation.updated_at = _utcnow()
        self._session.flush()
        return invocation
