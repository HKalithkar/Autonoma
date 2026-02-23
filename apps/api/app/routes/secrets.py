from __future__ import annotations

import os
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from libs.common.context import set_request_context

from ..db import session_scope
from ..secrets import resolve_secret_ref

router = APIRouter(prefix="/v1/secrets", tags=["secrets"])


class SecretResolveRequest(BaseModel):
    ref: str = Field(min_length=1)
    tenant_id: str | None = None
    actor_id: str | None = None


def _require_service_token(request: Request) -> None:
    expected = os.getenv("SERVICE_TOKEN")
    token = request.headers.get("x-service-token")
    if not expected or not token or token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


@router.post("/resolve")
def resolve_secret(payload: SecretResolveRequest, request: Request) -> dict[str, Any]:
    _require_service_token(request)
    correlation_id = request.headers.get("x-correlation-id") or str(uuid.uuid4())
    actor_id = payload.actor_id or "service:secret-resolver"
    tenant_id = payload.tenant_id or "default"
    set_request_context(
        correlation_id=correlation_id,
        actor_id=actor_id,
        tenant_id=tenant_id,
    )
    with session_scope() as session:
        secret = resolve_secret_ref(
            session,
            ref=payload.ref,
            context={
                "correlation_id": correlation_id,
                "actor_id": actor_id,
                "tenant_id": tenant_id,
            },
        )
    return {"status": "ok", "secret": secret}
