from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any

import httpx


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_llm_audit_event(
    *,
    agent_type: str,
    correlation_id: str,
    actor_id: str,
    tenant_id: str,
    model: str,
    api_url: str,
    prompt: str,
    response: str,
    latency_ms: float,
    status: str,
    error_code: str | None = None,
) -> dict[str, Any]:
    prompt_hash = _hash_text(prompt)
    response_hash = _hash_text(response)
    details: dict[str, Any] = {
        "agent_type": agent_type,
        "model": model,
        "api_url": api_url,
        "prompt_hash": prompt_hash,
        "prompt_chars": len(prompt),
        "response_hash": response_hash,
        "response_chars": len(response),
        "latency_ms": round(latency_ms, 2),
        "status": status,
    }
    if error_code:
        details["error_code"] = error_code
    if os.getenv("LLM_LOG_SUMMARY", "false").lower() == "true":
        details["summary"] = response[:240]
    return {
        "event_type": "llm.call",
        "outcome": "allow" if status == "ok" else "deny",
        "details": details,
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "tenant_id": tenant_id,
        "source": "agent-runtime",
        "created_at": _utcnow().isoformat(),
    }


def emit_audit_events(events: list[dict[str, Any]]) -> None:
    base_url = os.getenv("AUDIT_INGEST_URL", "http://api:8000/v1/audit/ingest")
    token = os.getenv("AUDIT_INGEST_TOKEN")
    if not token:
        return
    headers = {"x-service-token": token}
    try:
        httpx.post(base_url, headers=headers, json=events, timeout=5.0)
    except httpx.RequestError:
        return
