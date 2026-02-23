from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from fastapi import HTTPException, status

from libs.common.context import get_request_context
from libs.common.metrics import PLUGIN_INVOCATIONS

from .audit import audit_event
from .models import Plugin, PluginInvocation, Workflow
from .secrets import resolve_secret_ref

_SENSITIVE_KEYS = {"token", "secret", "password", "apikey", "api_key", "authorization"}
_SECRET_PREFIX = "secretkeyref:"
_LOGGER = logging.getLogger("autonoma.runner")


def _is_secret_ref(value: str) -> bool:
    return value.startswith(_SECRET_PREFIX)


def _resolve_value(
    value: Any,
    *,
    session,
    context: dict[str, str],
    parent_key: str | None,
) -> tuple[Any, Any]:
    if isinstance(value, dict):
        resolved: dict[str, Any] = {}
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            item_resolved, item_redacted = _resolve_value(
                item, session=session, context=context, parent_key=key
            )
            resolved[key] = item_resolved
            redacted[key] = item_redacted
        return resolved, redacted
    if isinstance(value, list):
        resolved_list = []
        redacted_list = []
        for item in value:
            item_resolved, item_redacted = _resolve_value(
                item, session=session, context=context, parent_key=parent_key
            )
            resolved_list.append(item_resolved)
            redacted_list.append(item_redacted)
        return resolved_list, redacted_list
    if isinstance(value, str) and _is_secret_ref(value):
        secret = resolve_secret_ref(session, ref=value, context=context)
        if parent_key and parent_key.lower() in _SENSITIVE_KEYS:
            return secret, "[REDACTED]"
        return secret, value
    if isinstance(value, str) and value.startswith("env:"):
        env_var = value.split("env:", 1)[1]
        env_secret = os.getenv(env_var)
        if env_secret is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Secret not found",
            )
        if parent_key and parent_key.lower() in _SENSITIVE_KEYS:
            return env_secret, "[REDACTED]"
        return env_secret, value
    if parent_key and parent_key.lower() in _SENSITIVE_KEYS:
        return value, "[REDACTED]"
    return value, value


def resolve_secret_refs(
    session,
    params: dict[str, Any],
    *,
    context: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved_params: dict[str, Any] = {}
    redacted_params: dict[str, Any] = {}
    for key, value in params.items():
        resolved_value, redacted_value = _resolve_value(
            value,
            session=session,
            context=context,
            parent_key=key,
        )
        resolved_params[key] = resolved_value
        redacted_params[key] = redacted_value
    return resolved_params, redacted_params


def invoke_workflow_plugin(
    session,
    workflow: Workflow,
    params: dict[str, Any],
    workflow_run_id: str | None = None,
) -> dict[str, Any]:
    plugin = session.get(Plugin, workflow.plugin_id)
    if not plugin:
        raise ValueError("Plugin not found")

    context = get_request_context()
    context = get_request_context()
    invoke_params, redacted_params = resolve_secret_refs(
        session,
        params,
        context={
            "correlation_id": context.correlation_id,
            "actor_id": context.actor_id,
            "tenant_id": context.tenant_id,
        },
    )
    if plugin.name == "gitops" and workflow_run_id:
        invoke_params["workflow_run_id"] = workflow_run_id
        redacted_params["workflow_run_id"] = workflow_run_id
    invoke_payload = {
        "plugin": plugin.name,
        "action": workflow.action,
        "params": invoke_params,
        "context": {
            "correlation_id": context.correlation_id,
            "actor_id": context.actor_id,
            "tenant_id": context.tenant_id,
        },
    }
    headers = {}
    token = os.getenv("PLUGIN_GATEWAY_TOKEN") or os.getenv("SERVICE_TOKEN")
    if token:
        headers["x-service-token"] = token
    try:
        response = httpx.post(
            plugin.endpoint,
            json=invoke_payload,
            headers=headers,
            timeout=5.0,
        )
        response.raise_for_status()
        result = response.json()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        detail = exc.response.text.strip() if exc.response.text else "Upstream error"
        _LOGGER.warning(
            "plugin_gateway_error plugin=%s action=%s status=%s correlation_id=%s actor_id=%s",
            plugin.name,
            workflow.action,
            status_code,
            context.correlation_id,
            context.actor_id,
        )
        audit_event(
            "plugin.invoke",
            "deny",
            {
                "plugin": plugin.name,
                "action": workflow.action,
                "status_code": status_code,
                "error": detail[:200],
            },
            session=session,
        )
        PLUGIN_INVOCATIONS.labels(
            plugin=plugin.name,
            action=workflow.action,
            status="error",
        ).inc()
        if 400 <= status_code < 500:
            raise HTTPException(status_code=status_code, detail=detail) from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Plugin gateway unavailable",
        ) from exc
    except httpx.RequestError as exc:
        _LOGGER.warning(
            "plugin_gateway_unavailable plugin=%s action=%s correlation_id=%s actor_id=%s error=%s",
            plugin.name,
            workflow.action,
            context.correlation_id,
            context.actor_id,
            exc,
        )
        audit_event(
            "plugin.invoke",
            "deny",
            {
                "plugin": plugin.name,
                "action": workflow.action,
                "status_code": status.HTTP_502_BAD_GATEWAY,
                "error": "plugin_gateway_unavailable",
            },
            session=session,
        )
        PLUGIN_INVOCATIONS.labels(
            plugin=plugin.name,
            action=workflow.action,
            status="error",
        ).inc()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Plugin gateway unavailable",
        ) from exc

    job_id = result.get("job_id")
    invocation = PluginInvocation(
        plugin_id=plugin.id,
        action=workflow.action,
        status=result.get("status", "submitted"),
        params=redacted_params,
        result={"job_id": job_id},
        correlation_id=context.correlation_id,
        actor_id=context.actor_id,
        tenant_id=context.tenant_id,
    )
    session.add(invocation)
    audit_event(
        "plugin.invoke",
        "allow",
        {
            "plugin": plugin.name,
            "action": workflow.action,
            "job_id": job_id,
        },
        session=session,
    )
    PLUGIN_INVOCATIONS.labels(
        plugin=plugin.name,
        action=workflow.action,
        status=result.get("status", "submitted"),
    ).inc()
    if plugin.name == "gitops":
        return {
            "status": result.get("status", "submitted"),
            "job_id": job_id,
            "gitops": {
                "job_id": job_id,
                "callback_url": result.get("callback_url"),
            },
        }
    return result
