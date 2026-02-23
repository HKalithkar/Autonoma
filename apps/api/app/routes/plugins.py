from __future__ import annotations

import os
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from libs.common.context import set_request_context
from libs.common.metrics import PLUGIN_REGISTRY, PLUGINS_TOTAL

from ..audit import audit_event
from ..db import session_scope
from ..models import Plugin, Workflow
from ..rbac import require_permission

router = APIRouter(prefix="/v1/plugins", tags=["plugins"])

_PLUGIN_TYPES = {"workflow", "secret", "mcp", "api", "other"}
_AUTH_TYPES = {"none", "basic", "bearer", "api_key", "oauth", "mtls", "secret_ref"}

def _require_service_token(request: Request) -> None:
    expected = os.getenv("SERVICE_TOKEN")
    token = request.headers.get("x-service-token")
    if not expected or not token or token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


@router.get("")
def list_plugins(
    plugin_type: str | None = None,
    name: str | None = None,
    ctx=require_permission("plugin:read"),
) -> list[dict[str, Any]]:
    with session_scope() as session:
        query = session.query(Plugin)
        if plugin_type:
            if plugin_type not in _PLUGIN_TYPES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid plugin_type"
                )
            query = query.filter(Plugin.plugin_type == plugin_type)
        if name:
            query = query.filter(Plugin.name == name)
        plugins = query.all()
        PLUGINS_TOTAL.labels(tenant_id=ctx.tenant_id).set(len(plugins))
        return [
            {
                "id": str(plugin.id),
                "name": plugin.name,
                "version": plugin.version,
                "plugin_type": plugin.plugin_type,
                "endpoint": plugin.endpoint,
                "actions": plugin.actions,
                "allowed_roles": plugin.allowed_roles,
                "auth_type": plugin.auth_type,
                "auth_ref": plugin.auth_ref,
                "auth_config": plugin.auth_config,
            }
            for plugin in plugins
        ]


@router.get("/internal/resolve")
def resolve_plugin_internal(
    request: Request,
    name: str,
    plugin_type: str | None = None,
) -> dict[str, Any]:
    _require_service_token(request)
    if plugin_type and plugin_type not in _PLUGIN_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid plugin_type")
    correlation_id = request.headers.get("x-correlation-id") or str(uuid.uuid4())
    actor_id = request.headers.get("x-actor-id") or "service:plugin-gateway"
    tenant_id = request.headers.get("x-tenant-id") or "default"
    set_request_context(
        correlation_id=correlation_id,
        actor_id=actor_id,
        tenant_id=tenant_id,
    )
    with session_scope() as session:
        query = session.query(Plugin).filter(Plugin.name == name, Plugin.tenant_id == tenant_id)
        if plugin_type:
            query = query.filter(Plugin.plugin_type == plugin_type)
        plugin = query.first()
        if not plugin:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found")
        audit_event(
            "plugin.resolve",
            "allow",
            {"plugin": plugin.name, "plugin_type": plugin.plugin_type},
            session=session,
        )
        return {
            "name": plugin.name,
            "plugin_type": plugin.plugin_type,
            "endpoint": plugin.endpoint,
            "auth_type": plugin.auth_type,
            "auth_ref": plugin.auth_ref,
            "auth_config": plugin.auth_config,
        }


@router.post("", status_code=status.HTTP_201_CREATED)
def register_plugin(
    payload: dict[str, Any],
    ctx=require_permission("plugin:write"),
) -> dict[str, Any]:
    name = str(payload.get("name", "")).strip()
    endpoint = str(payload.get("endpoint", "")).strip()
    actions = payload.get("actions", {})
    plugin_type = str(payload.get("plugin_type", "workflow")).strip().lower()
    auth_type = str(payload.get("auth_type", "none")).strip().lower()
    auth_ref = payload.get("auth_ref")
    auth_config = payload.get("auth_config", {}) or {}
    if not name or not endpoint:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing fields")
    if plugin_type not in _PLUGIN_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid plugin_type")
    if auth_type not in _AUTH_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid auth_type")
    if auth_type in {"basic", "bearer", "api_key", "oauth", "secret_ref"} and not auth_ref:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing auth_ref")
    with session_scope() as session:
        plugin = Plugin(
            name=name,
            version=payload.get("version", "v1"),
            plugin_type=plugin_type,
            endpoint=endpoint,
            actions=actions,
            allowed_roles=payload.get("allowed_roles", {}),
            auth_type=auth_type,
            auth_ref=auth_ref,
            auth_config=auth_config,
            tenant_id=ctx.tenant_id,
        )
        session.add(plugin)
        session.flush()
        audit_event("plugin.register", "allow", {"plugin_id": str(plugin.id)}, session=session)
        PLUGIN_REGISTRY.labels(action="register", plugin_type=plugin.plugin_type).inc()
        return {"id": str(plugin.id), "name": plugin.name}


@router.put("/{plugin_id}", status_code=status.HTTP_200_OK)
def update_plugin(
    plugin_id: str,
    payload: dict[str, Any],
    ctx=require_permission("plugin:write"),
) -> dict[str, Any]:
    name = str(payload.get("name", "")).strip()
    endpoint = str(payload.get("endpoint", "")).strip()
    actions = payload.get("actions", {})
    plugin_type = str(payload.get("plugin_type", "workflow")).strip().lower()
    auth_type = str(payload.get("auth_type", "none")).strip().lower()
    auth_ref = payload.get("auth_ref")
    auth_config = payload.get("auth_config", {}) or {}
    if not name or not endpoint:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing fields")
    if plugin_type not in _PLUGIN_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid plugin_type")
    if auth_type not in _AUTH_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid auth_type")
    if auth_type in {"basic", "bearer", "api_key", "oauth", "secret_ref"} and not auth_ref:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing auth_ref")

    try:
        plugin_uuid = uuid.UUID(plugin_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid plugin id",
        ) from exc

    with session_scope() as session:
        plugin = session.get(Plugin, plugin_uuid)
        if not plugin:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found")
        plugin.name = name
        plugin.endpoint = endpoint
        plugin.version = payload.get("version", plugin.version)
        plugin.plugin_type = plugin_type
        plugin.actions = actions
        plugin.allowed_roles = payload.get("allowed_roles", plugin.allowed_roles or {})
        plugin.auth_type = auth_type
        plugin.auth_ref = auth_ref
        plugin.auth_config = auth_config
        session.flush()
        audit_event("plugin.update", "allow", {"plugin_id": str(plugin.id)}, session=session)
        PLUGIN_REGISTRY.labels(action="update", plugin_type=plugin.plugin_type).inc()
        return {"id": str(plugin.id), "name": plugin.name}


@router.delete("/{plugin_id}", status_code=status.HTTP_200_OK)
def delete_plugin(
    plugin_id: str,
    ctx=require_permission("plugin:write"),
) -> dict[str, Any]:
    try:
        plugin_uuid = uuid.UUID(plugin_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid plugin id",
        ) from exc
    with session_scope() as session:
        plugin = session.get(Plugin, plugin_uuid)
        if not plugin:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found")
        usage = session.query(Workflow).filter(Workflow.plugin_id == plugin.id).count()
        if usage:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Plugin has registered workflows",
            )
        session.delete(plugin)
        audit_event("plugin.delete", "allow", {"plugin_id": str(plugin.id)}, session=session)
        PLUGIN_REGISTRY.labels(action="delete", plugin_type=plugin.plugin_type).inc()
        session.flush()
        return {"status": "deleted", "plugin_id": str(plugin.id)}
