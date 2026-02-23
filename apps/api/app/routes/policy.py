from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..policy import evaluate_policy
from ..rbac import require_permission

router = APIRouter(prefix="/v1/policy", tags=["policy"])


@router.post("/check")
def policy_check(
    payload: dict[str, Any],
    ctx=require_permission("policy:read"),
) -> dict[str, Any]:
    action = str(payload.get("action", ""))
    resource = dict(payload.get("resource", {}))
    parameters = dict(payload.get("parameters", {}))
    decision = evaluate_policy(action, resource, parameters)
    return {
        "allow": decision.allow,
        "deny_reasons": decision.deny_reasons,
        "required_approvals": decision.required_approvals,
        "actor_id": ctx.actor_id,
        "tenant_id": ctx.tenant_id,
    }
