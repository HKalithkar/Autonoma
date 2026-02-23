import logging
import os
import time
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST
from pydantic import BaseModel, Field

from libs.common.metrics import render_metrics
from libs.common.otel import init_otel, instrument_fastapi

from .chat import ChatRequest, ChatResponse, generate_chat_response
from .llm import LLMResolutionError, resolve_api_key, resolve_llm_config
from .planner import AgentPlanRequest, AgentPlanResponse
from .vector_store import VectorStoreError, build_records, get_vector_store

app = FastAPI(title="Autonoma Agent Runtime", version="0.0.0")
init_otel(os.getenv("SERVICE_NAME", "agent-runtime"))
instrument_fastapi(app)
logger = logging.getLogger("autonoma.agent_runtime")


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    filters: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any]


class MemorySearchResponse(BaseModel):
    results: list[dict[str, Any]]


class MemoryIngestRequest(BaseModel):
    texts: list[str] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any]


_LLM_READY: dict[str, str] = {"status": "unknown", "detail": "startup", "checked_at": "0"}


def _check_llm_readiness() -> None:
    from libs.common.llm_defaults import load_llm_defaults

    defaults = load_llm_defaults()
    config = resolve_llm_config("user_chat", defaults)
    api_key = resolve_api_key(
        config.api_key_ref,
        correlation_id="readiness-check",
        actor_id="service:agent-runtime",
        tenant_id="default",
    )
    if not api_key:
        raise LLMResolutionError("missing_api_key")


def _readiness_recheck_seconds() -> float:
    raw = os.getenv("LLM_READINESS_RECHECK_SECONDS", "10")
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 10.0


def _launch_v1_run_from_plan(payload: AgentPlanRequest) -> AgentPlanResponse:
    token = os.getenv("SERVICE_TOKEN")
    if not token:
        raise HTTPException(status_code=500, detail="Missing SERVICE_TOKEN")
    orchestrator_url = os.getenv("RUNTIME_ORCHESTRATOR_URL", "http://runtime-orchestrator:8003").rstrip(
        "/"
    )
    try:
        response = httpx.post(
            f"{orchestrator_url}/v1/orchestrator/runs",
            headers={"x-service-token": token},
            json={
                "intent": payload.goal,
                "environment": payload.environment,
                "metadata": {
                    "source": "legacy_v0_agent_plan_adapter",
                    "tools": payload.tools,
                    "documents": payload.documents,
                    "execute_tools": payload.execute_tools,
                },
                "context": {
                    "correlation_id": payload.context.correlation_id,
                    "actor_id": payload.context.actor_id,
                    "tenant_id": payload.context.tenant_id,
                    "actor_name": payload.context.actor_id,
                },
            },
            timeout=5.0,
        )
        response.raise_for_status()
        launched = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Runtime orchestrator unavailable") from exc
    run_id = str(launched.get("run_id") or "")
    return AgentPlanResponse(
        plan_id=f"v1-run-{run_id}",
        status="planned",
        plan=[],
        tool_calls=[],
        memory_refs=[],
        traces=[
            {
                "event": "legacy.adapter.v1_run_launch",
                "run_id": run_id,
                "status": str(launched.get("status") or "running"),
            }
        ],
    )


def _refresh_llm_readiness(*, force: bool = False) -> None:
    now = time.monotonic()
    last_checked = float(_LLM_READY.get("checked_at", "0"))
    if not force and (now - last_checked) < _readiness_recheck_seconds():
        return
    _LLM_READY["checked_at"] = str(now)
    try:
        _check_llm_readiness()
    except LLMResolutionError as exc:
        _LLM_READY["status"] = "error"
        _LLM_READY["detail"] = str(exc)
        logger.warning("llm_readiness_failed reason=%s", exc)
    except Exception as exc:
        _LLM_READY["status"] = "error"
        _LLM_READY["detail"] = "readiness_check_failed"
        logger.warning("llm_readiness_failed reason=%s", exc)
    else:
        _LLM_READY["status"] = "ok"
        _LLM_READY["detail"] = "ready"


@app.on_event("startup")
def _startup_checks() -> None:
    _refresh_llm_readiness(force=True)


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"status": "ok", "llm": {"status": _LLM_READY["status"], "detail": _LLM_READY["detail"]}}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    if _LLM_READY["status"] != "ok":
        _refresh_llm_readiness()
    if _LLM_READY["status"] != "ok":
        raise HTTPException(status_code=503, detail=_LLM_READY["detail"])
    return {"status": "ready"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(content=render_metrics(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/agent/plan", response_model=AgentPlanResponse)
def plan(payload: AgentPlanRequest) -> AgentPlanResponse:
    if not payload.goal.strip():
        raise HTTPException(status_code=400, detail="Missing goal")
    return _launch_v1_run_from_plan(payload)


@app.post("/v1/chat/respond", response_model=ChatResponse)
def chat_respond(payload: ChatRequest) -> ChatResponse:
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Missing message")
    return generate_chat_response(payload)


@app.post("/v1/memory/search", response_model=MemorySearchResponse)
def memory_search(payload: MemorySearchRequest, request: Request) -> MemorySearchResponse:
    _require_service_token(request)
    tenant_id = str(payload.context.get("tenant_id") or "default")
    try:
        store = get_vector_store()
        results = store.query(tenant_id, payload.query, payload.top_k, payload.filters)
    except VectorStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Vector store unavailable") from exc
    return MemorySearchResponse(
        results=[
            {
                "id": item.id,
                "score": item.score,
                "text": item.text,
                "metadata": item.metadata,
            }
            for item in results
        ]
    )


def _require_service_token(request: Request) -> None:
    expected = os.getenv("SERVICE_TOKEN")
    if not expected:
        return
    token = request.headers.get("x-service-token")
    if token != expected:
        raise HTTPException(status_code=401, detail="Invalid token")


@app.post("/v1/memory/ingest")
def memory_ingest(payload: MemoryIngestRequest, request: Request) -> dict[str, Any]:
    _require_service_token(request)
    tenant_id = str(payload.context.get("tenant_id") or "default")
    try:
        store = get_vector_store()
        records = build_records(
            tenant_id=tenant_id,
            texts=payload.texts,
            metadata=payload.metadata,
        )
        ids = store.upsert_texts(tenant_id, records)
    except VectorStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Vector store unavailable") from exc
    return {"status": "ok", "count": len(ids)}
