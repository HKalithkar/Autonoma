from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, status

from ..audit import audit_event
from ..rbac import require_permission

router = APIRouter(prefix="/v1/iam", tags=["iam"])


def _iam_settings() -> dict[str, str]:
    provider = os.getenv("IAM_PROVIDER", "").strip().lower()
    admin_url = os.getenv("IAM_ADMIN_URL", "").strip()
    token_url = os.getenv("IAM_TOKEN_URL", "").strip() or os.getenv("OIDC_TOKEN_URL", "").strip()
    client_id = os.getenv("IAM_CLIENT_ID", "").strip()
    client_secret = os.getenv("IAM_CLIENT_SECRET", "").strip()
    realm = os.getenv("IAM_REALM", "").strip()
    if not realm:
        issuer = os.getenv("OIDC_ISSUER", "")
        if "/realms/" in issuer:
            realm = issuer.split("/realms/", 1)[1].split("/", 1)[0]
    return {
        "provider": provider,
        "admin_url": admin_url,
        "token_url": token_url,
        "client_id": client_id,
        "client_secret": client_secret,
        "realm": realm,
    }


def _require_config(settings: dict[str, str]) -> None:
    if settings["provider"] != "keycloak":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="IAM provider not configured",
        )
    if not settings["admin_url"] or not settings["token_url"]:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="IAM admin endpoints not configured",
        )
    if not settings["client_id"] or not settings["client_secret"]:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="IAM admin credentials not configured",
        )
    if not settings["realm"]:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="IAM realm not configured",
        )


def _fetch_token(settings: dict[str, str]) -> str:
    response = httpx.post(
        settings["token_url"],
        data={
            "grant_type": "client_credentials",
            "client_id": settings["client_id"],
            "client_secret": settings["client_secret"],
        },
        timeout=5.0,
    )
    try:
        response.raise_for_status()
        payload = response.json()
    except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="IAM token request failed",
        ) from exc
    token = payload.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="IAM token missing",
        )
    return str(token)


def _admin_base(settings: dict[str, str]) -> str:
    return f"{settings['admin_url'].rstrip('/')}/admin/realms/{settings['realm']}"


@router.get("/status")
def iam_status(ctx=require_permission("iam:read")) -> dict[str, Any]:
    settings = _iam_settings()
    configured = (
        settings["provider"] == "keycloak"
        and settings["admin_url"]
        and settings["token_url"]
        and settings["client_id"]
        and settings["client_secret"]
        and settings["realm"]
    )
    return {
        "provider": settings["provider"] or "disabled",
        "configured": configured,
        "admin_url": settings["admin_url"],
        "realm": settings["realm"],
    }


@router.get("/users")
def list_users(ctx=require_permission("iam:read")) -> list[dict[str, Any]]:
    settings = _iam_settings()
    _require_config(settings)
    token = _fetch_token(settings)
    response = httpx.get(
        f"{_admin_base(settings)}/users",
        headers={"Authorization": f"Bearer {token}"},
        params={"max": 50},
        timeout=5.0,
    )
    try:
        response.raise_for_status()
        payload = response.json()
    except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="IAM user list failed",
        ) from exc
    audit_event("iam.users.list", "allow", {"count": len(payload)})
    return [
        {
            "id": item.get("id"),
            "username": item.get("username"),
            "email": item.get("email"),
            "enabled": item.get("enabled", False),
            "created_timestamp": item.get("createdTimestamp"),
        }
        for item in payload or []
    ]


@router.get("/roles")
def list_roles(ctx=require_permission("iam:read")) -> list[dict[str, Any]]:
    settings = _iam_settings()
    _require_config(settings)
    token = _fetch_token(settings)
    response = httpx.get(
        f"{_admin_base(settings)}/roles",
        headers={"Authorization": f"Bearer {token}"},
        timeout=5.0,
    )
    try:
        response.raise_for_status()
        payload = response.json()
    except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="IAM role list failed",
        ) from exc
    audit_event("iam.roles.list", "allow", {"count": len(payload)})
    return [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "description": item.get("description"),
            "composite": item.get("composite", False),
        }
        for item in payload or []
    ]


@router.post("/users/{user_id}/roles")
def assign_roles(
    user_id: str,
    payload: dict[str, Any],
    ctx=require_permission("iam:write"),
) -> dict[str, Any]:
    roles = payload.get("roles")
    if not isinstance(roles, list) or not roles:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing roles")
    settings = _iam_settings()
    _require_config(settings)
    token = _fetch_token(settings)
    base = _admin_base(settings)
    resolved_roles: list[dict[str, Any]] = []
    for role in roles:
        role_name = str(role).strip()
        if not role_name:
            continue
        response = httpx.get(
            f"{base}/roles/{role_name}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
        )
        try:
            response.raise_for_status()
            role_payload = response.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"IAM role lookup failed: {role_name}",
            ) from exc
        resolved_roles.append(
            {
                "id": role_payload.get("id"),
                "name": role_payload.get("name"),
                "description": role_payload.get("description"),
                "composite": role_payload.get("composite", False),
                "clientRole": role_payload.get("clientRole", False),
                "containerId": role_payload.get("containerId"),
            }
        )
    if not resolved_roles:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No roles resolved")
    response = httpx.post(
        f"{base}/users/{user_id}/role-mappings/realm",
        headers={"Authorization": f"Bearer {token}"},
        json=resolved_roles,
        timeout=5.0,
    )
    try:
        response.raise_for_status()
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="IAM role assignment failed",
        ) from exc
    audit_event("iam.roles.assign", "allow", {"user_id": user_id, "roles": roles})
    return {"status": "ok", "user_id": user_id, "roles": roles}


@router.get("/users/{user_id}/roles")
def list_user_roles(user_id: str, ctx=require_permission("iam:read")) -> list[dict[str, Any]]:
    settings = _iam_settings()
    _require_config(settings)
    token = _fetch_token(settings)
    response = httpx.get(
        f"{_admin_base(settings)}/users/{user_id}/role-mappings/realm",
        headers={"Authorization": f"Bearer {token}"},
        timeout=5.0,
    )
    try:
        response.raise_for_status()
        payload = response.json()
    except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="IAM user roles lookup failed",
        ) from exc
    audit_event("iam.user.roles.list", "allow", {"user_id": user_id, "count": len(payload or [])})
    return [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "description": item.get("description"),
            "composite": item.get("composite", False),
        }
        for item in payload or []
    ]
