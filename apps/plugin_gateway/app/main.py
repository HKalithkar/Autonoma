from __future__ import annotations

import asyncio
import json
import os
from base64 import b64encode
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response, status
from prometheus_client import CONTENT_TYPE_LATEST
from pydantic import BaseModel, Field

from libs.common.audit import audit_event
from libs.common.context import set_request_context
from libs.common.metrics import render_metrics
from libs.common.otel import init_otel, instrument_fastapi

app = FastAPI(title="Autonoma Plugin Gateway", version="0.0.0")
init_otel(os.getenv("SERVICE_NAME", "plugin-gateway"))
instrument_fastapi(app)


class InvocationContext(BaseModel):
    correlation_id: str
    actor_id: str
    tenant_id: str


class InvocationRequest(BaseModel):
    plugin: str
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    context: InvocationContext


class InvocationResponse(BaseModel):
    status: str
    job_id: str
    result: dict[str, Any] | None = None
    callback_url: str | None = None


class GitOpsWebhook(BaseModel):
    workflow_run_id: str
    status: str
    commit_sha: str | None = None
    pr_url: str | None = None
    pipeline_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class PolicyDecision(BaseModel):
    allow: bool
    deny_reasons: list[str] = Field(default_factory=list)
    required_approvals: list[str] = Field(default_factory=list)


class PluginRecord(BaseModel):
    name: str
    plugin_type: str
    endpoint: str
    auth_type: str
    auth_ref: str | None = None
    auth_config: dict[str, Any] = Field(default_factory=dict)


class MCPError(BaseModel):
    code: int | None = None
    message: str | None = None
    data: dict[str, Any] | None = None


class MCPResponse(BaseModel):
    result: dict[str, Any] | None = None
    error: MCPError | None = None


_MCP_ACTIONS = {"tools/list", "tools/call"}
_WORKFLOW_FORWARD_CONFIG_KEY = "invoke_url"
_TRANSIENT_STATUS_CODES = {429, 502, 503, 504}


def _http_retry_config() -> tuple[int, float]:
    raw_attempts = os.getenv("PLUGIN_GATEWAY_HTTP_MAX_ATTEMPTS", "3")
    raw_backoff = os.getenv("PLUGIN_GATEWAY_HTTP_RETRY_BACKOFF_SECONDS", "0.2")
    try:
        attempts = max(1, int(raw_attempts))
    except ValueError:
        attempts = 3
    try:
        backoff_seconds = max(0.0, float(raw_backoff))
    except ValueError:
        backoff_seconds = 0.2
    return attempts, backoff_seconds


def _is_transient_http_error(exc: httpx.HTTPError) -> bool:
    if isinstance(
        exc,
        (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout),
    ):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _TRANSIENT_STATUS_CODES
    return False


async def _request_with_retry(method: str, url: str, **kwargs: Any) -> httpx.Response:
    attempts, backoff_seconds = _http_retry_config()
    last_error: httpx.HTTPError | None = None
    limits = httpx.Limits(
        max_connections=int(os.getenv("PLUGIN_GATEWAY_HTTP_MAX_CONNECTIONS", "500")),
        max_keepalive_connections=int(
            os.getenv("PLUGIN_GATEWAY_HTTP_MAX_KEEPALIVE_CONNECTIONS", "200")
        ),
    )
    timeout = kwargs.pop("timeout", 5.0)
    for attempt in range(1, attempts + 1):
        try:
            async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
                response = await client.request(method, url, **kwargs)
                response.raise_for_status()
                return response
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt >= attempts or not _is_transient_http_error(exc):
                raise
            await asyncio.sleep(backoff_seconds * attempt)
    assert last_error is not None  # pragma: no cover
    raise last_error  # pragma: no cover


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    opa_url = os.getenv("OPA_URL", "http://policy:8181").rstrip("/")
    api_url = os.getenv("API_URL", "http://api:8000").rstrip("/")
    dependency_checks = {
        "policy": f"{opa_url}/health",
        "api": f"{api_url}/healthz",
    }
    failures: dict[str, str] = {}
    for dependency, target in dependency_checks.items():
        try:
            await _request_with_retry("GET", target, timeout=2.0)
        except httpx.HTTPError:
            failures[dependency] = "unreachable"
    if failures:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "dependencies": failures},
        )
    return {"status": "ready"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(content=render_metrics(), media_type=CONTENT_TYPE_LATEST)


def _require_service_token(request: Request) -> None:
    expected = os.getenv("PLUGIN_GATEWAY_TOKEN") or os.getenv("SERVICE_TOKEN")
    if expected and request.headers.get("x-service-token") != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


async def _evaluate_policy(
    *,
    action: str,
    resource: dict[str, Any],
    parameters: dict[str, Any],
    context: InvocationContext,
) -> PolicyDecision:
    opa_url = os.getenv("OPA_URL", "http://policy:8181")
    input_payload = {
        "actor_id": context.actor_id,
        "tenant_id": context.tenant_id,
        "correlation_id": context.correlation_id,
        "action": action,
        "resource": resource,
        "parameters": parameters,
    }
    response = await _request_with_retry(
        "POST",
        f"{opa_url}/v1/data/autonoma/decision",
        json={"input": input_payload},
        headers={"x-correlation-id": context.correlation_id},
        timeout=5.0,
    )
    payload = response.json().get("result", {})
    return PolicyDecision(
        allow=bool(payload.get("allow", False)),
        deny_reasons=list(payload.get("deny_reasons", [])),
        required_approvals=list(payload.get("required_approvals", [])),
    )


async def _resolve_secret_ref(ref: str, *, context: InvocationContext) -> str:
    if not ref:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing auth_ref")
    if not ref.startswith("secretkeyref:"):
        return ref
    api_url = os.getenv("API_URL", "http://api:8000").rstrip("/")
    token = os.getenv("SERVICE_TOKEN")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Missing SERVICE_TOKEN"
        )
    response = await _request_with_retry(
        "POST",
        f"{api_url}/v1/secrets/resolve",
        headers={
            "x-service-token": token,
            "x-correlation-id": context.correlation_id,
            "x-actor-id": context.actor_id,
            "x-tenant-id": context.tenant_id,
        },
        json={
            "ref": ref,
            "tenant_id": context.tenant_id,
            "actor_id": context.actor_id,
        },
        timeout=5.0,
    )
    payload = response.json()
    return str(payload.get("secret", ""))


def _resolve_auth_ref(auth_ref: str) -> str:
    if not auth_ref:
        return ""
    if auth_ref.startswith("env:"):
        env_key = auth_ref.split(":", 1)[1]
        value = os.getenv(env_key)
        if not value:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Missing secret env: {env_key}",
            )
        return value
    if auth_ref.startswith("secretkeyref:"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nested secret references are not supported",
        )
    return auth_ref


async def _build_auth_headers(
    plugin: PluginRecord, *, context: InvocationContext
) -> dict[str, str]:
    auth_type = plugin.auth_type
    auth_ref = plugin.auth_ref or ""
    config = plugin.auth_config or {}
    if auth_type == "none":
        return {}
    if auth_type == "bearer":
        token = await _resolve_secret_ref(auth_ref, context=context)
        return {"authorization": f"Bearer {token}"}
    if auth_type == "api_key":
        header_name = str(config.get("header_name", "x-api-key"))
        token = await _resolve_secret_ref(auth_ref, context=context)
        return {header_name: token}
    if auth_type == "basic":
        username = str(config.get("username", "")).strip()
        if not username:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing username")
        password = await _resolve_secret_ref(auth_ref, context=context)
        encoded = b64encode(f"{username}:{password}".encode("utf-8")).decode("utf-8")
        return {"authorization": f"Basic {encoded}"}
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unsupported auth_type: {auth_type}",
    )


def _workflow_invoke_url(plugin: PluginRecord) -> str:
    raw_url = str(plugin.auth_config.get(_WORKFLOW_FORWARD_CONFIG_KEY, "")).strip()
    if not raw_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing invoke_url"
        )
    return raw_url


async def _fetch_plugin_record(
    *,
    name: str,
    plugin_type: str | None,
    context: InvocationContext,
) -> PluginRecord:
    api_url = os.getenv("API_URL", "http://api:8000").rstrip("/")
    token = os.getenv("SERVICE_TOKEN")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Missing SERVICE_TOKEN"
        )
    params = {"name": name}
    if plugin_type:
        params["plugin_type"] = plugin_type
    response = await _request_with_retry(
        "GET",
        f"{api_url}/v1/plugins/internal/resolve",
        headers={
            "x-service-token": token,
            "x-correlation-id": context.correlation_id,
            "x-actor-id": context.actor_id,
            "x-tenant-id": context.tenant_id,
        },
        params=params,
        timeout=5.0,
    )
    return PluginRecord(**response.json())


async def _invoke_mcp(
    *,
    endpoint: str,
    method: str,
    params: dict[str, Any],
    headers: dict[str, str],
    context: InvocationContext,
) -> dict[str, Any]:
    response = await _request_with_retry(
        "POST",
        endpoint,
        json={
            "jsonrpc": "2.0",
            "id": context.correlation_id,
            "method": method,
            "params": params,
        },
        headers=headers,
        timeout=10.0,
    )
    payload = MCPResponse(**response.json())
    if payload.error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": payload.error.model_dump()},
        )
    return payload.result or {}


async def _resolve_secret(params: dict[str, Any]) -> str:
    auth_config = params.get("auth_config") or {}
    provider = str(params.get("provider") or auth_config.get("provider", "")).strip().lower()
    if provider == "vault":
        return await _resolve_vault_secret(params)
    return _resolve_secret_map(params)


def _resolve_secret_map(params: dict[str, Any]) -> str:
    ref = str(params.get("ref", "")).strip()
    path = str(params.get("path", "")).strip()
    plugin = str(params.get("plugin", "")).strip()
    if not ref:
        if path:
            ref = f"{plugin}:{path}" if plugin else path
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing ref")
    raw_map = os.getenv("SECRET_STORE_MAP", "{}")
    try:
        mapping = json.loads(raw_map)
    except json.JSONDecodeError:
        mapping = {}
    secret = mapping.get(ref)
    if secret:
        return str(secret)
    if path and plugin:
        secret = mapping.get(f"{plugin}:{path}")
        if secret:
            return str(secret)
    if path:
        secret = mapping.get(path)
        if secret:
            return str(secret)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Secret not found")


def _parse_vault_path(path: str, default_mount: str) -> tuple[str, str, str]:
    trimmed = path.strip().lstrip("/")
    if not trimmed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing secret path")
    key = ""
    if "#" in trimmed:
        trimmed, key = trimmed.split("#", 1)
        key = key.strip()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing secret key in path",
        )
    mount = default_mount.strip().strip("/")
    if trimmed.startswith(f"{mount}/"):
        trimmed = trimmed[len(mount) + 1 :]
    return mount, trimmed, key


async def _resolve_vault_secret(params: dict[str, Any]) -> str:
    auth_ref = str(params.get("auth_ref") or "").strip()
    auth_config = params.get("auth_config") or {}
    path = str(params.get("path") or params.get("ref") or "").strip()
    if not path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing ref")
    token = _resolve_auth_ref(auth_ref)
    if not token:
        token = os.getenv("VAULT_TOKEN", "")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Missing Vault token",
        )
    addr = str(auth_config.get("addr") or os.getenv("VAULT_ADDR", "http://vault:8200")).rstrip("/")
    mount = str(auth_config.get("mount") or os.getenv("VAULT_KV_MOUNT", "kv"))
    mount, secret_path, key = _parse_vault_path(path, mount)
    url = f"{addr}/v1/{mount}/data/{secret_path}"
    response = await _request_with_retry(
        "GET",
        url,
        headers={"X-Vault-Token": token},
        timeout=5.0,
    )
    payload = response.json()
    data = (payload.get("data") or {}).get("data") or {}
    if key not in data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Secret not found")
    value = data.get(key)
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Secret not found")
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


@app.post("/invoke", response_model=InvocationResponse)
async def invoke(request: InvocationRequest, http_request: Request) -> InvocationResponse:
    _require_service_token(http_request)
    set_request_context(
        correlation_id=request.context.correlation_id,
        actor_id=request.context.actor_id,
        tenant_id=request.context.tenant_id,
    )
    decision = await _evaluate_policy(
        action="plugin:invoke",
        resource={"plugin": request.plugin, "action": request.action},
        parameters={"params": {"keys": list(request.params.keys())}},
        context=request.context,
    )
    audit_event(
        "policy",
        "allow" if decision.allow else "deny",
        {
            "action": "plugin:invoke",
            "plugin": request.plugin,
            "plugin_action": request.action,
            "deny_reasons": decision.deny_reasons,
            "required_approvals": decision.required_approvals,
        },
    )
    if not decision.allow:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "deny_reasons": decision.deny_reasons,
                "required_approvals": decision.required_approvals,
            },
        )

    if request.action in _MCP_ACTIONS:
        plugin_record = await _fetch_plugin_record(
            name=request.plugin,
            plugin_type="mcp",
            context=request.context,
        )
        headers = await _build_auth_headers(plugin_record, context=request.context)
        try:
            result = await _invoke_mcp(
                endpoint=plugin_record.endpoint,
                method=request.action,
                params=request.params,
                headers=headers,
                context=request.context,
            )
        except HTTPException as exc:
            audit_event(
                "plugin.invoke",
                "deny",
                {
                    "plugin": request.plugin,
                    "action": request.action,
                    "plugin_type": "mcp",
                    "reason": exc.detail,
                },
            )
            raise
        audit_event(
            "plugin.invoke",
            "allow",
            {
                "plugin": request.plugin,
                "action": request.action,
                "plugin_type": "mcp",
                "job_id": f"mcp-{request.context.correlation_id}",
            },
        )
        return InvocationResponse(
            status="ok",
            job_id=f"mcp-{request.context.correlation_id}",
            result={"result": result},
        )

    if request.action == "resolve":
        try:
            secret = await _resolve_secret(request.params)
        except HTTPException as exc:
            audit_event(
                "secret.resolve",
                "deny",
                {
                    "ref": request.params.get("ref"),
                    "provider": request.params.get("provider"),
                    "reason": exc.detail,
                },
            )
            raise
        audit_event(
            "secret.resolve",
            "allow",
            {"ref": request.params.get("ref"), "provider": request.params.get("provider")},
        )
        return InvocationResponse(
            status="ok",
            job_id=f"secret-{request.context.correlation_id}",
            result={"secret": secret},
        )
    if request.plugin == "gitops" and request.action == "create_change":
        if "workflow_run_id" not in request.params:
            audit_event(
                "plugin.invoke",
                "deny",
                {
                    "plugin": request.plugin,
                    "action": request.action,
                    "reason": "missing_workflow_run",
                },
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Missing workflow_run_id"
            )
        job_id = f"gitops-{request.context.correlation_id}"
        callback_url = f"{os.getenv('GITOPS_WEBHOOK_URL', 'http://api:8000/v1/gitops/webhook')}"
        audit_event(
            "plugin.invoke",
            "allow",
            {"plugin": request.plugin, "action": request.action, "job_id": job_id},
        )
        return InvocationResponse(status="submitted", job_id=job_id, callback_url=callback_url)
    try:
        plugin_record = await _fetch_plugin_record(
            name=request.plugin,
            plugin_type="workflow",
            context=request.context,
        )
        invoke_url = _workflow_invoke_url(plugin_record)
        headers = await _build_auth_headers(plugin_record, context=request.context)
        headers.update(
            {
                "x-correlation-id": request.context.correlation_id,
                "x-actor-id": request.context.actor_id,
                "x-tenant-id": request.context.tenant_id,
            }
        )
        response = await _request_with_retry(
            "POST",
            invoke_url,
            json=request.model_dump(),
            headers=headers,
            timeout=5.0,
        )
    except HTTPException as exc:
        audit_event(
            "plugin.invoke",
            "deny",
            {
                "plugin": request.plugin,
                "action": request.action,
                "reason": exc.detail,
            },
        )
        raise
    except httpx.HTTPError as exc:
        audit_event(
            "plugin.invoke",
            "deny",
            {
                "plugin": request.plugin,
                "action": request.action,
                "reason": "forward_failed",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Plugin forwarding failed"
        ) from exc

    payload = response.json()
    job_id = str(payload.get("job_id") or f"workflow-{request.context.correlation_id}")
    audit_event(
        "plugin.invoke",
        "allow",
        {"plugin": request.plugin, "action": request.action, "job_id": job_id},
    )
    return InvocationResponse(
        status=str(payload.get("status", "submitted")),
        job_id=job_id,
        result=payload.get("result"),
        callback_url=payload.get("callback_url"),
    )


@app.post("/gitops/webhook")
async def gitops_webhook(payload: GitOpsWebhook) -> dict[str, Any]:
    token = os.getenv("GITOPS_WEBHOOK_TOKEN", "")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Missing token"
        )
    set_request_context(
        correlation_id=payload.workflow_run_id,
        actor_id="service:gitops",
        tenant_id=payload.details.get("tenant_id", "default"),
    )
    audit_event(
        "gitops.webhook.forward",
        "allow",
        {"workflow_run_id": payload.workflow_run_id, "status": payload.status},
    )
    await _request_with_retry(
        "POST",
        os.getenv("GITOPS_WEBHOOK_URL", "http://api:8000/v1/gitops/webhook"),
        headers={"x-service-token": token},
        json=payload.model_dump(),
        timeout=5.0,
    )
    return {"status": "ok"}
