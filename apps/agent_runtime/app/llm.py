from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
from opentelemetry.trace import Status, StatusCode
from pydantic import SecretStr

from libs.common.llm_config import validate_api_key_ref
from libs.common.metrics import LLM_CALLS, LLM_LATENCY_MS

from .audit import build_llm_audit_event, emit_audit_events
from .tracing import (
    full_trace_enabled,
    get_tracer,
    hash_text,
    redact_preview,
    set_span_attributes,
    set_span_context,
)


@dataclass(frozen=True)
class LLMConfig:
    agent_type: str
    api_url: str
    model: str
    api_key_ref: str | None = None


class LLMResolutionError(RuntimeError):
    pass


def _is_timeout_error(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return True
    name = exc.__class__.__name__.lower()
    if "timeout" in name:
        return True
    return "timed out" in str(exc).lower()


def resolve_llm_config(
    agent_type: str,
    defaults: dict[str, dict[str, Any]],
    overrides: dict[str, dict[str, Any]] | None = None,
) -> LLMConfig:
    base = defaults.get(agent_type)
    if not base:
        raise LLMResolutionError(f"missing_defaults:{agent_type}")
    merged = dict(base)
    if overrides and agent_type in overrides:
        merged.update({k: v for k, v in overrides[agent_type].items() if v is not None})
    api_url = str(merged.get("api_url", "")).strip()
    model = str(merged.get("model", "")).strip()
    api_key_ref = str(merged.get("api_key_ref") or "").strip() or None
    if not api_url or not model:
        raise LLMResolutionError(f"missing_config:{agent_type}")
    try:
        validate_api_key_ref(api_key_ref)
    except ValueError as exc:
        raise LLMResolutionError("invalid_api_key_ref") from exc
    return LLMConfig(
        agent_type=agent_type,
        api_url=api_url,
        model=model,
        api_key_ref=api_key_ref,
    )


_SECRET_PREFIX = "secretkeyref:"


def _resolve_secret_via_api(
    api_key_ref: str,
    *,
    correlation_id: str,
    actor_id: str,
    tenant_id: str,
) -> str | None:
    token = os.getenv("SERVICE_TOKEN")
    if not token:
        raise LLMResolutionError("missing_service_token")
    timeout = float(os.getenv("SECRET_RESOLVER_TIMEOUT", "5.0"))
    try:
        response = httpx.post(
            os.getenv("SECRET_RESOLVER_URL", "http://api:8000/v1/secrets/resolve"),
            headers={"x-service-token": token, "x-correlation-id": correlation_id},
            json={"ref": api_key_ref, "tenant_id": tenant_id, "actor_id": actor_id},
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
    except httpx.TimeoutException as exc:
        raise LLMResolutionError("secret_resolver_timeout") from exc
    except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
        raise LLMResolutionError("secret_resolution_failed") from exc
    return data.get("secret")


def resolve_api_key(
    api_key_ref: str | None,
    *,
    correlation_id: str,
    actor_id: str,
    tenant_id: str,
) -> str | None:
    if not api_key_ref:
        return os.getenv("LLM_API_KEY")
    if api_key_ref.startswith("env:"):
        env_var = api_key_ref.split("env:", 1)[1]
        return os.getenv(env_var)
    if api_key_ref.startswith(_SECRET_PREFIX):
        return _resolve_secret_via_api(
            api_key_ref,
            correlation_id=correlation_id,
            actor_id=actor_id,
            tenant_id=tenant_id,
        )
    return os.getenv("LLM_API_KEY")


def get_chat_model(
    config: LLMConfig,
    *,
    correlation_id: str,
    actor_id: str,
    tenant_id: str,
    fake_response: str | None = None,
) -> Any:
    if os.getenv("AUTONOMA_FAKE_LLM") == "1":
        return _FakeChatModel(
            fake_response or "{}",
            config=config,
            correlation_id=correlation_id,
            actor_id=actor_id,
            tenant_id=tenant_id,
        )
    api_key = resolve_api_key(
        config.api_key_ref,
        correlation_id=correlation_id,
        actor_id=actor_id,
        tenant_id=tenant_id,
    )
    if not api_key:
        raise LLMResolutionError("missing_api_key")
    return _AuditedChatModel(
        ChatOpenAI(
            api_key=SecretStr(api_key),
            base_url=config.api_url,
            model=config.model,
            temperature=0.2,
            timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "15")),
            max_retries=2,
        ),
        config=config,
        correlation_id=correlation_id,
        actor_id=actor_id,
        tenant_id=tenant_id,
    )


class _FakeChatModel:
    def __init__(
        self,
        response: str,
        *,
        config: LLMConfig,
        correlation_id: str,
        actor_id: str,
        tenant_id: str,
    ) -> None:
        self._response = response
        self._config = config
        self._correlation_id = correlation_id
        self._actor_id = actor_id
        self._tenant_id = tenant_id

    def invoke(self, messages: list[Any]) -> AIMessage:
        start = time.perf_counter()
        prompt = json.dumps([_normalize_message(message) for message in messages])
        tracer = get_tracer()
        with tracer.start_as_current_span("llm.invoke") as span:
            set_span_context(
                span,
                correlation_id=self._correlation_id,
                actor_id=self._actor_id,
                tenant_id=self._tenant_id,
            )
            prompt_preview, prompt_redacted, prompt_truncated = redact_preview(prompt)
            trace_input = prompt if full_trace_enabled() else prompt_preview
            set_span_attributes(
                span,
                {
                    "llm.agent_type": self._config.agent_type,
                    "llm.model": self._config.model,
                    "llm.api_url": self._config.api_url,
                    "llm.input_preview": prompt_preview,
                    "llm.input_redacted": prompt_redacted,
                    "llm.input_truncated": prompt_truncated,
                    "llm.input_chars": len(prompt),
                    "llm.input_sha256": hash_text(prompt),
                    "langfuse.observation.input": trace_input,
                    "gen_ai.prompt": trace_input,
                },
            )
            response = AIMessage(content=self._response)
            output_preview, output_redacted, output_truncated = redact_preview(self._response)
            trace_output = self._response if full_trace_enabled() else output_preview
            set_span_attributes(
                span,
                {
                    "llm.output_preview": output_preview,
                    "llm.output_redacted": output_redacted,
                    "llm.output_truncated": output_truncated,
                    "llm.output_chars": len(self._response),
                    "llm.output_sha256": hash_text(self._response),
                    "langfuse.observation.output": trace_output,
                    "gen_ai.completion": trace_output,
                },
            )
        latency_ms = (time.perf_counter() - start) * 1000
        event = build_llm_audit_event(
            agent_type=self._config.agent_type,
            correlation_id=self._correlation_id,
            actor_id=self._actor_id,
            tenant_id=self._tenant_id,
            model=self._config.model,
            api_url=self._config.api_url,
            prompt=prompt,
            response=self._response,
            latency_ms=latency_ms,
            status="ok",
        )
        emit_audit_events([event])
        LLM_CALLS.labels(
            agent_type=self._config.agent_type,
            status="ok",
            model=self._config.model,
        ).inc()
        LLM_LATENCY_MS.labels(
            agent_type=self._config.agent_type,
            status="ok",
        ).observe(latency_ms)
        return response


class _AuditedChatModel:
    def __init__(
        self,
        inner: Any,
        *,
        config: LLMConfig,
        correlation_id: str,
        actor_id: str,
        tenant_id: str,
    ) -> None:
        self._inner = inner
        self._config = config
        self._correlation_id = correlation_id
        self._actor_id = actor_id
        self._tenant_id = tenant_id

    def invoke(self, messages: list[Any]) -> Any:
        start = time.perf_counter()
        prompt = json.dumps([_normalize_message(message) for message in messages])
        status = "ok"
        response_text = ""
        error_code = None
        tracer = get_tracer()
        with tracer.start_as_current_span("llm.invoke") as span:
            set_span_context(
                span,
                correlation_id=self._correlation_id,
                actor_id=self._actor_id,
                tenant_id=self._tenant_id,
            )
            prompt_preview, prompt_redacted, prompt_truncated = redact_preview(prompt)
            trace_input = prompt if full_trace_enabled() else prompt_preview
            set_span_attributes(
                span,
                {
                    "llm.agent_type": self._config.agent_type,
                    "llm.model": self._config.model,
                    "llm.api_url": self._config.api_url,
                    "llm.input_preview": prompt_preview,
                    "llm.input_redacted": prompt_redacted,
                    "llm.input_truncated": prompt_truncated,
                    "llm.input_chars": len(prompt),
                    "llm.input_sha256": hash_text(prompt),
                    "langfuse.observation.input": trace_input,
                    "gen_ai.prompt": trace_input,
                },
            )
            try:
                response = self._inner.invoke(messages)
                response_text = getattr(response, "content", "") or ""
                output_preview, output_redacted, output_truncated = redact_preview(response_text)
                trace_output = response_text if full_trace_enabled() else output_preview
                set_span_attributes(
                    span,
                    {
                        "llm.output_preview": output_preview,
                        "llm.output_redacted": output_redacted,
                        "llm.output_truncated": output_truncated,
                        "llm.output_chars": len(response_text),
                        "llm.output_sha256": hash_text(response_text),
                        "langfuse.observation.output": trace_output,
                        "gen_ai.completion": trace_output,
                    },
                )
                return response
            except Exception as exc:
                status = "error"
                if _is_timeout_error(exc):
                    error_code = "LLM_TIMEOUT_SECONDS"
                    span.set_status(Status(StatusCode.ERROR, "llm_timeout"))
                else:
                    error_code = "LLM_INVOKE_ERROR"
                    span.set_status(Status(StatusCode.ERROR, "llm_invoke_error"))
                set_span_attributes(span, {"llm.error_code": error_code})
                span.record_exception(exc)
                raise
            finally:
                latency_ms = (time.perf_counter() - start) * 1000
                event = build_llm_audit_event(
                    agent_type=self._config.agent_type,
                    correlation_id=self._correlation_id,
                    actor_id=self._actor_id,
                    tenant_id=self._tenant_id,
                    model=self._config.model,
                    api_url=self._config.api_url,
                    prompt=prompt,
                    response=response_text,
                    latency_ms=latency_ms,
                    status=status,
                    error_code=error_code,
                )
                emit_audit_events([event])
                LLM_CALLS.labels(
                    agent_type=self._config.agent_type,
                    status=status,
                    model=self._config.model,
                ).inc()
                LLM_LATENCY_MS.labels(
                    agent_type=self._config.agent_type,
                    status=status,
                ).observe(latency_ms)


def _normalize_message(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        return message
    if hasattr(message, "type") and hasattr(message, "content"):
        return {"type": str(message.type), "content": str(message.content)}
    if hasattr(message, "content"):
        return {"type": message.__class__.__name__, "content": str(message.content)}
    return {"type": "unknown", "content": str(message)}
