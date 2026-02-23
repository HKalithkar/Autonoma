from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel, Field

app = FastAPI(title="Autonoma Workflow Adapter", version="0.0.0")


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


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    return {"status": "ready"}


def _require_service_token(request: Request) -> None:
    expected = os.getenv("WORKFLOW_ADAPTER_TOKEN") or ""
    if not expected:
        return
    token = request.headers.get("x-service-token")
    if token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def _parse_action(action: str) -> tuple[str, str | None]:
    if ":" in action:
        base, target = action.split(":", 1)
        return base, target or None
    return action, None


async def _resolve_secret_value(value: str, *, context: InvocationContext) -> str:
    if not value:
        return value
    if value.startswith("env:"):
        env_key = value.split(":", 1)[1]
        resolved = os.getenv(env_key)
        if not resolved:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Missing secret env: {env_key}",
            )
        return resolved
    if value.startswith("secretkeyref:"):
        resolver_url = os.getenv("SECRET_RESOLVER_URL", "http://api:8000/v1/secrets/resolve")
        token = os.getenv("SERVICE_TOKEN")
        if not token:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Missing SERVICE_TOKEN",
            )
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                resolver_url,
                headers={
                    "x-service-token": token,
                    "x-correlation-id": context.correlation_id,
                    "x-actor-id": context.actor_id,
                    "x-tenant-id": context.tenant_id,
                },
                json={
                    "ref": value,
                    "tenant_id": context.tenant_id,
                    "actor_id": context.actor_id,
                },
            )
            response.raise_for_status()
        payload = response.json()
        secret = payload.get("secret")
        if not secret:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Secret not found",
            )
        return str(secret)
    return value


async def _airflow_settings(context: InvocationContext) -> tuple[str, str, str]:
    base_url = os.getenv("AIRFLOW_URL", "http://airflow:8080").rstrip("/")
    username = os.getenv("AIRFLOW_USERNAME", "admin")
    raw_password = (
        os.getenv("AIRFLOW_PASSWORD_REF")
        or os.getenv("AIRFLOW_PASSWORD")
        or "admin"
    )
    password = await _resolve_secret_value(raw_password, context=context)
    return base_url, username, password


async def _jenkins_settings(context: InvocationContext) -> tuple[str, str | None, str | None]:
    base_url = os.getenv("JENKINS_URL", "http://jenkins:8080").rstrip("/")
    user = os.getenv("JENKINS_USER") or None
    raw_token = os.getenv("JENKINS_TOKEN_REF") or os.getenv("JENKINS_TOKEN") or ""
    token = await _resolve_secret_value(raw_token, context=context) if raw_token else None
    return base_url, user, token


def _n8n_settings() -> str:
    return os.getenv("N8N_BASE_URL", "http://n8n:5678").rstrip("/")


async def _post_status_callback(
    *,
    context: InvocationContext,
    run_id: str,
    plugin: str,
    status_value: str,
    job_id: str,
    details: dict[str, Any],
) -> None:
    callback_url = os.getenv(
        "WORKFLOW_STATUS_CALLBACK_URL",
        "http://api:8000/v1/runs/internal/status",
    ).rstrip("/")
    token = os.getenv("SERVICE_TOKEN")
    if not token:
        return
    payload = {
        "run_id": run_id,
        "status": status_value,
        "job_id": job_id,
        "plugin": plugin,
        "tenant_id": context.tenant_id,
        "details": details,
    }
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(
            callback_url,
            headers={"x-service-token": token},
            json=payload,
        )
        response.raise_for_status()


async def _trigger_airflow(request: InvocationRequest) -> InvocationResponse:
    base_action, target = _parse_action(request.action)
    if base_action not in {"trigger_dag", "airflow.trigger_dag"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported action")

    dag_id = str(request.params.get("dag_id") or target or "").strip()
    if not dag_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing dag_id")

    base_url, username, password = await _airflow_settings(request.context)
    run_id = str(request.params.get("run_id") or f"autonoma-{request.context.correlation_id}")
    conf = request.params.get("conf") or {}
    payload = {"dag_run_id": run_id, "conf": conf}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{base_url}/api/v1/dags/{dag_id}/dagRuns",
                json=payload,
                auth=(username, password),
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Airflow invocation failed"
        ) from exc

    data = response.json()
    job_id = str(data.get("dag_run_id") or run_id)
    return InvocationResponse(
        status="submitted",
        job_id=job_id,
        result={"dag_id": dag_id, "dag_run_id": job_id},
    )


async def _trigger_jenkins(request: InvocationRequest) -> InvocationResponse:
    base_action, target = _parse_action(request.action)
    if base_action not in {"trigger_job", "jenkins.trigger_job"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported action")

    job_name = str(request.params.get("job_name") or target or "").strip()
    if not job_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing job_name")

    base_url, user, token = await _jenkins_settings(request.context)
    parameters = request.params.get("parameters") or {}
    endpoint = f"{base_url}/job/{job_name}"
    if parameters:
        endpoint = f"{endpoint}/buildWithParameters"
    else:
        endpoint = f"{endpoint}/build"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            request_kwargs: dict[str, Any] = {"params": parameters or None}
            if user and token:
                request_kwargs["auth"] = (user, token)
            response = await client.post(endpoint, **request_kwargs)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Jenkins invocation failed"
        ) from exc

    location = response.headers.get("location", "")
    queue_id = location.rstrip("/").split("/")[-1] if location else ""
    job_id = queue_id or f"queue-{request.context.correlation_id}"
    return InvocationResponse(
        status="submitted",
        job_id=job_id,
        result={"job_name": job_name, "queue_id": job_id},
    )


async def _trigger_n8n(request: InvocationRequest) -> InvocationResponse:
    base_action, target = _parse_action(request.action)
    if base_action not in {"trigger_workflow", "n8n.trigger_workflow"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported action")

    path = str(request.params.get("webhook_path") or target or "").strip().lstrip("/")
    if not path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing webhook_path",
        )

    workflow_payload = request.params.get("payload")
    if not isinstance(workflow_payload, dict):
        workflow_payload = dict(request.params)

    runtime_meta = request.params.get("_autonoma")
    runtime_run_id = ""
    if isinstance(runtime_meta, dict):
        runtime_run_id = str(runtime_meta.get("runtime_run_id") or "").strip()

    request_url = f"{_n8n_settings()}/webhook/{path}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(request_url, json=workflow_payload)
            response.raise_for_status()
            body = response.json() if response.headers.get("content-type", "").startswith(
                "application/json"
            ) else {"raw": response.text}
    except httpx.HTTPError as exc:
        if runtime_run_id:
            try:
                await _post_status_callback(
                    context=request.context,
                    run_id=runtime_run_id,
                    plugin="n8n",
                    status_value="failed",
                    job_id=runtime_run_id,
                    details={"error": "n8n invocation failed", "webhook_path": path},
                )
            except httpx.HTTPError:
                pass
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="n8n invocation failed",
        ) from exc

    callback_status = "succeeded"
    if isinstance(body, dict):
        raw_status = str(body.get("status") or "").strip().lower()
        if raw_status in {"failed", "error"}:
            callback_status = "failed"

    if runtime_run_id:
        try:
            await _post_status_callback(
                context=request.context,
                run_id=runtime_run_id,
                plugin="n8n",
                status_value=callback_status,
                job_id=runtime_run_id,
                details={"webhook_path": path, "response": body},
            )
        except httpx.HTTPError:
            pass

    return InvocationResponse(
        status="running",
        job_id=runtime_run_id or request.context.correlation_id,
        result={"workflow_path": path, "response": body, "callback_status": callback_status},
    )


@app.post("/invoke", response_model=InvocationResponse)
async def invoke(request: InvocationRequest, http_request: Request) -> InvocationResponse:
    _require_service_token(http_request)
    plugin = request.plugin.strip().lower()
    if plugin == "airflow":
        return await _trigger_airflow(request)
    if plugin == "jenkins":
        return await _trigger_jenkins(request)
    if plugin == "n8n":
        return await _trigger_n8n(request)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown plugin")
