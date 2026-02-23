from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ..audit_forwarder import forward_audit_event
from ..db import session_scope
from ..models import AuditEvent
from ..rbac import require_permission

router = APIRouter(prefix="/v1/audit", tags=["audit"])


class AuditIngestItem(BaseModel):
    event_type: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str
    actor_id: str
    tenant_id: str
    source: str = Field(min_length=1)
    created_at: datetime | None = None


@router.get("")
def list_audit_events(
    limit: int = 100,
    source: str | None = None,
    event_type: str | None = None,
    actor_id: str | None = None,
    outcome: str | None = None,
    since: str | None = None,
    until: str | None = None,
    ctx=require_permission("audit:read"),
) -> list[dict[str, Any]]:
    def _normalize(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    limit = max(1, min(limit, 200))
    source = _normalize(source)
    event_type = _normalize(event_type)
    actor_id = _normalize(actor_id)
    outcome = _normalize(outcome)
    since = _normalize(since)
    until = _normalize(until)
    since_dt: datetime | None = None
    until_dt: datetime | None = None
    try:
        if since:
            since_dt = datetime.fromisoformat(since)
        if until:
            until_dt = datetime.fromisoformat(until)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid timestamp filter",
        ) from exc
    with session_scope() as session:
        query = session.query(AuditEvent)
        if source:
            query = query.filter(AuditEvent.source.ilike(f"%{source}%"))
        if event_type:
            query = query.filter(AuditEvent.event_type.ilike(f"%{event_type}%"))
        if actor_id:
            query = query.filter(AuditEvent.actor_id.ilike(f"%{actor_id}%"))
        if outcome:
            query = query.filter(AuditEvent.outcome.ilike(f"%{outcome}%"))
        if since_dt:
            query = query.filter(AuditEvent.created_at >= since_dt)
        if until_dt:
            query = query.filter(AuditEvent.created_at <= until_dt)
        events = query.order_by(AuditEvent.created_at.desc()).limit(limit).all()
        return [
            {
                "id": str(event.id),
                "event_type": event.event_type,
                "outcome": event.outcome,
                "source": event.source,
                "details": event.details,
                "correlation_id": event.correlation_id,
                "actor_id": event.actor_id,
                "tenant_id": event.tenant_id,
                "created_at": event.created_at.isoformat(),
            }
            for event in events
        ]


@router.post("/ingest")
def ingest_audit_events(
    payload: list[AuditIngestItem],
    ctx=require_permission("audit:write"),
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        for item in payload:
            created_at = item.created_at or now
            forward_audit_event(
                {
                    "event_type": item.event_type,
                    "outcome": item.outcome,
                    "source": item.source,
                    "correlation_id": item.correlation_id,
                    "actor_id": item.actor_id,
                    "tenant_id": item.tenant_id,
                    "details": item.details,
                    "timestamp": created_at.isoformat(),
                }
            )
            event = AuditEvent(
                event_type=item.event_type,
                outcome=item.outcome,
                source=item.source,
                details=item.details,
                correlation_id=item.correlation_id,
                actor_id=item.actor_id,
                tenant_id=item.tenant_id,
                created_at=created_at,
            )
            session.add(event)
        session.flush()
    return {"status": "ok", "count": len(payload)}
