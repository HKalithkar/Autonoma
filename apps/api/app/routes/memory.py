from __future__ import annotations

import hashlib
import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from libs.common.context import get_request_context

from ..audit import audit_event
from ..rbac import require_permission

router = APIRouter(prefix="/v1/memory", tags=["memory"])


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    filters: dict[str, Any] = Field(default_factory=dict)


@router.post("/search")
def search_memory(
    payload: MemorySearchRequest,
    ctx=require_permission("memory:read"),
) -> dict[str, Any]:
    context = get_request_context()
    query_hash = hashlib.sha256(payload.query.encode("utf-8")).hexdigest()
    agent_payload = {
        "query": payload.query,
        "top_k": payload.top_k,
        "filters": payload.filters,
        "context": {
            "correlation_id": context.correlation_id,
            "actor_id": context.actor_id,
            "tenant_id": context.tenant_id,
        },
    }
    try:
        headers: dict[str, str] = {}
        service_token = os.getenv("SERVICE_TOKEN")
        if service_token:
            headers["x-service-token"] = service_token
        response = httpx.post(
            "http://agent-runtime:8001/v1/memory/search",
            headers=headers or None,
            json=agent_payload,
            timeout=5.0,
        )
        response.raise_for_status()
    except httpx.RequestError as exc:
        audit_event(
            "memory.search",
            "deny",
            {
                "reason": "agent_runtime_unavailable",
                "query_hash": query_hash,
                "query_chars": len(payload.query),
                "top_k": payload.top_k,
                "filter_keys": sorted(payload.filters.keys()),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Agent runtime unavailable",
        ) from exc
    result = response.json()
    audit_event(
        "memory.search",
        "allow",
        {
            "query_hash": query_hash,
            "query_chars": len(payload.query),
            "top_k": payload.top_k,
            "filter_keys": sorted(payload.filters.keys()),
            "result_count": len(result.get("results", [])),
        },
    )
    return result
