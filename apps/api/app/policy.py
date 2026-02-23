from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from libs.common.context import get_request_context

from .audit import audit_event


@dataclass(frozen=True)
class PolicyDecision:
    allow: bool
    deny_reasons: list[str]
    required_approvals: list[str]


@dataclass(frozen=True)
class PolicySettings:
    opa_url: str


def get_policy_settings() -> PolicySettings:
    return PolicySettings(opa_url=os.getenv("OPA_URL", "http://policy:8181"))


def _decision_from_response(payload: dict[str, Any]) -> PolicyDecision:
    decision = payload.get("result", {})
    return PolicyDecision(
        allow=bool(decision.get("allow", False)),
        deny_reasons=list(decision.get("deny_reasons", [])),
        required_approvals=list(decision.get("required_approvals", [])),
    )


def evaluate_policy(
    action: str,
    resource: dict[str, Any],
    parameters: dict[str, Any],
) -> PolicyDecision:
    settings = get_policy_settings()
    context = get_request_context()
    input_payload = {
        "actor_id": context.actor_id,
        "tenant_id": context.tenant_id,
        "correlation_id": context.correlation_id,
        "action": action,
        "resource": resource,
        "parameters": parameters,
    }
    response = httpx.post(
        f"{settings.opa_url}/v1/data/autonoma/decision",
        json={"input": input_payload},
        headers={"x-correlation-id": context.correlation_id},
        timeout=5.0,
    )
    response.raise_for_status()
    decision = _decision_from_response(response.json())
    audit_event(
        "policy",
        "allow" if decision.allow else "deny",
        {
            "action": action,
            "deny_reasons": decision.deny_reasons,
            "required_approvals": decision.required_approvals,
        },
    )
    return decision
