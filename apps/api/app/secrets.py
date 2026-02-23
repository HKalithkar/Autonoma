from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import HTTPException, status

from .audit import audit_event
from .models import Plugin


def parse_secret_ref(ref: str) -> tuple[str, str]:
    parts = ref.split(":", 3)
    if len(parts) != 4 or parts[0] != "secretkeyref" or parts[1] != "plugin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid secret reference"
        )
    plugin_name = parts[2].strip()
    path = parts[3].strip()
    if not plugin_name or not path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid secret reference"
        )
    return plugin_name, path


def resolve_secret_ref(
    session,
    *,
    ref: str,
    context: dict[str, str],
) -> str:
    plugin_name, path = parse_secret_ref(ref)
    plugin = (
        session.query(Plugin)
        .filter_by(name=plugin_name, plugin_type="secret", tenant_id=context["tenant_id"])
        .one_or_none()
    )
    if not plugin:
        audit_event(
            "secret.resolve",
            "deny",
            {"ref": ref, "reason": "plugin_not_found", "plugin": plugin_name},
            session=session,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Secret plugin not found"
        )
    token = os.getenv("PLUGIN_GATEWAY_TOKEN") or os.getenv("SERVICE_TOKEN")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Missing plugin gateway token",
        )
    payload: dict[str, Any] = {
        "plugin": plugin.name,
        "action": "resolve",
        "params": {
            "path": path,
            "ref": ref,
            "plugin": plugin.name,
            "auth_type": plugin.auth_type,
            "auth_ref": plugin.auth_ref,
            "auth_config": plugin.auth_config,
        },
        "context": context,
    }
    response = httpx.post(
        plugin.endpoint,
        headers={"x-service-token": token},
        json=payload,
        timeout=5.0,
    )
    try:
        response.raise_for_status()
        data = response.json()
    except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Secret resolution failed",
        ) from exc
    result = data.get("result") or {}
    secret = result.get("secret")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Secret not found"
        )
    audit_event(
        "secret.resolve",
        "allow",
        {"ref": ref, "plugin": plugin.name},
        session=session,
    )
    return str(secret)
