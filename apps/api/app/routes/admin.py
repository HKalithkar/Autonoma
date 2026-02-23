from __future__ import annotations

from fastapi import APIRouter

from ..rbac import require_permission

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.get("/permissions")
def permissions_check(ctx=require_permission("rbac:read")) -> dict[str, object]:
    return {
        "actor_id": ctx.actor_id,
        "tenant_id": ctx.tenant_id,
        "roles": ctx.roles,
        "permissions": ctx.permissions,
    }
