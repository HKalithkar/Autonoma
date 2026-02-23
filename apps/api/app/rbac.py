from __future__ import annotations

from typing import Iterable

from fastapi import Depends, HTTPException, Request, status

from .auth import (
    AuthContext,
    audit_authz_decision,
    ensure_token,
    extract_roles,
    extract_tenant_id,
    update_request_context,
)

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "viewer": {"auth:me"},
    "operator": {
        "auth:me",
        "workflow:read",
        "workflow:run",
        "agent:run",
        "chat:run",
        "memory:read",
    },
    "approver": {
        "auth:me",
        "workflow:read",
        "workflow:run",
        "approval:read",
        "approval:write",
        "agent:run",
        "chat:run",
        "memory:read",
    },
    "admin": {
        "auth:me",
        "workflow:*",
        "workflow:write",
        "approval:*",
        "plugin:*",
        "rbac:*",
        "audit:*",
        "policy:*",
        "agent:*",
        "chat:*",
        "memory:*",
        "iam:*",
    },
    "security_admin": {
        "auth:me",
        "workflow:read",
        "approval:*",
        "audit:*",
        "policy:*",
        "memory:read",
    },
    "service_audit": {"audit:write"},
}


def permissions_for_roles(roles: Iterable[str]) -> set[str]:
    permissions: set[str] = set()
    for role in roles:
        permissions.update(ROLE_PERMISSIONS.get(role, set()))
    return permissions


def _allows(permission: str, permissions: set[str]) -> bool:
    if permission in permissions:
        return True
    prefix = permission.split(":")[0]
    return f"{prefix}:*" in permissions


def require_permission(permission: str):
    def _dependency(request: Request) -> AuthContext:
        claims = ensure_token(request)
        roles = extract_roles(claims)
        tenant_id = extract_tenant_id(claims, request)
        update_request_context(request, claims)
        username = (
            str(
                claims.get("preferred_username")
                or claims.get("email")
                or claims.get("name")
                or ""
            ).strip()
            or None
        )
        permissions = permissions_for_roles(roles)
        if not _allows(permission, permissions):
            audit_authz_decision(permission, "deny")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        audit_authz_decision(permission, "allow")
        actor_id = str(claims.get("sub") or claims.get("preferred_username") or "unknown")
        return AuthContext(
            actor_id=actor_id,
            tenant_id=tenant_id,
            roles=roles,
            permissions=sorted(permissions),
            username=username,
        )

    return Depends(_dependency)
