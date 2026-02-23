"""Request-scoped context for correlation and identity."""

from __future__ import annotations

import contextvars
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestContext:
    correlation_id: str
    actor_id: str
    tenant_id: str


_correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default="unknown"
)
_actor_id: contextvars.ContextVar[str] = contextvars.ContextVar("actor_id", default="anonymous")
_tenant_id: contextvars.ContextVar[str] = contextvars.ContextVar("tenant_id", default="default")


def set_request_context(correlation_id: str, actor_id: str, tenant_id: str) -> None:
    _correlation_id.set(correlation_id)
    _actor_id.set(actor_id)
    _tenant_id.set(tenant_id)


def get_request_context() -> RequestContext:
    return RequestContext(
        correlation_id=_correlation_id.get(),
        actor_id=_actor_id.get(),
        tenant_id=_tenant_id.get(),
    )
