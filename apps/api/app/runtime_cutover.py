from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import HTTPException, status


def launch_v1_run(
    *,
    intent: str,
    environment: str,
    metadata: dict[str, Any],
    correlation_id: str,
    actor_id: str,
    actor_name: str | None,
    tenant_id: str,
) -> dict[str, Any]:
    token = os.getenv("SERVICE_TOKEN")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Missing SERVICE_TOKEN",
        )
    orchestrator_url = os.getenv("RUNTIME_ORCHESTRATOR_URL", "http://runtime-orchestrator:8003").rstrip(
        "/"
    )
    try:
        response = httpx.post(
            f"{orchestrator_url}/v1/orchestrator/runs",
            headers={"x-service-token": token},
            json={
                "intent": intent,
                "environment": environment,
                "metadata": metadata,
                "context": {
                    "correlation_id": correlation_id,
                    "actor_id": actor_id,
                    "tenant_id": tenant_id,
                    "actor_name": actor_name,
                },
            },
            timeout=15.0,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Runtime orchestrator timed out",
        ) from exc
    except httpx.HTTPStatusError as exc:
        detail = "Runtime orchestrator returned an error"
        if exc.response is not None:
            body = (exc.response.text or "").strip()
            if body:
                detail = f"Runtime orchestrator error ({exc.response.status_code}): {body}"
            else:
                detail = f"Runtime orchestrator error ({exc.response.status_code})"
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=detail,
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Runtime orchestrator unavailable",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid orchestrator response",
        )
    return payload
