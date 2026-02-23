from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

from libs.common.llm_defaults import load_llm_defaults

from .llm import (
    LLMConfig,
    LLMResolutionError,
    _is_timeout_error,
    get_chat_model,
    resolve_llm_config,
)
from .tracing import get_tracer, set_span_attributes, set_span_context

logger = logging.getLogger("autonoma.agent_runtime.chat")


@dataclass(frozen=True)
class ChatContext:
    message: str
    history: list[dict[str, str]]
    context: "ChatRequest.Context"
    llm_config: LLMConfig
    fake_response: str | None = None


class ChatRequest(BaseModel):
    class Context(BaseModel):
        correlation_id: str = Field(min_length=1)
        actor_id: str = Field(min_length=1)
        tenant_id: str = Field(default="default", min_length=1)

    message: str = Field(min_length=1)
    history: list[dict[str, str]] = Field(default_factory=list)
    context: Context
    llm_overrides: dict[str, dict[str, Any]] | None = None
    fake_response: str | None = None


class ChatToolCall(BaseModel):
    action: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    response: str
    tool_calls: list[ChatToolCall] = Field(default_factory=list)
    error_code: str | None = None


def _map_resolution_error(exc: LLMResolutionError) -> str:
    code = str(exc)
    if code == "secret_resolver_timeout":
        return "SECRET_RESOLVER_TIMEOUT"
    return "LLM_RESOLUTION_ERROR"


def _load_prompt() -> str:
    prompt_path = Path(__file__).resolve().parent / "prompts" / "chat.txt"
    if not prompt_path.exists():
        prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "chat.txt"
    return prompt_path.read_text()


def _render_history(history: list[dict[str, str]]) -> str:
    lines = []
    for item in history:
        role = item.get("role", "user")
        content = item.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def generate_chat_response(payload: ChatRequest) -> ChatResponse:
    defaults = load_llm_defaults()
    llm_config = resolve_llm_config("user_chat", defaults, payload.llm_overrides)
    context = ChatContext(
        message=payload.message,
        history=payload.history,
        context=payload.context,
        llm_config=llm_config,
        fake_response=payload.fake_response,
    )
    system_prompt = _load_prompt().replace("{{message}}", context.message)
    system_prompt = system_prompt.replace("{{history}}", _render_history(context.history))

    tracer = get_tracer()
    with tracer.start_as_current_span("chat.generate") as span:
        set_span_context(
            span,
            correlation_id=context.context.correlation_id,
            actor_id=context.context.actor_id,
            tenant_id=context.context.tenant_id,
        )
        set_span_attributes(
            span,
            {
                "chat.history_count": len(context.history),
                "chat.message_chars": len(context.message),
                "llm.model": context.llm_config.model,
                "llm.api_url": context.llm_config.api_url,
            },
        )
        try:
            llm = get_chat_model(
                context.llm_config,
                correlation_id=context.context.correlation_id,
                actor_id=context.context.actor_id,
                tenant_id=context.context.tenant_id,
                fake_response=context.fake_response,
            )
            response = llm.invoke(
                [SystemMessage(content=system_prompt), HumanMessage(content=context.message)]
            )
            content = getattr(response, "content", "")
        except LLMResolutionError as exc:
            error_code = _map_resolution_error(exc)
            set_span_attributes(
                span,
                {
                    "chat.status": "error",
                    "chat.error_code": error_code,
                },
            )
            logger.warning(
                "Chat unavailable (llm_resolution_error=%s) correlation_id=%s "
                "actor_id=%s tenant_id=%s model=%s api_url=%s",
                exc,
                context.context.correlation_id,
                context.context.actor_id,
                context.context.tenant_id,
                context.llm_config.model,
                context.llm_config.api_url,
            )
            return ChatResponse(
                response="Chat unavailable.",
                tool_calls=[],
                error_code=error_code,
            )
        except Exception as exc:
            error_code = "LLM_TIMEOUT_SECONDS" if _is_timeout_error(exc) else "LLM_INVOKE_ERROR"
            set_span_attributes(
                span,
                {
                    "chat.status": "error",
                    "chat.error_code": error_code,
                },
            )
            logger.exception(
                "Chat unavailable (llm_invoke_error) correlation_id=%s actor_id=%s "
                "tenant_id=%s model=%s api_url=%s",
                context.context.correlation_id,
                context.context.actor_id,
                context.context.tenant_id,
                context.llm_config.model,
                context.llm_config.api_url,
            )
            return ChatResponse(
                response="Chat unavailable.",
                tool_calls=[],
                error_code=error_code,
            )
        try:
            parsed = ChatResponse.model_validate_json(content)
        except ValidationError:
            set_span_attributes(
                span,
                {
                    "chat.status": "error",
                    "chat.error_code": "llm_parse_error",
                    "chat.response_chars": len(content or ""),
                },
            )
            logger.warning(
                "Chat response parse failed correlation_id=%s actor_id=%s tenant_id=%s "
                "model=%s api_url=%s response_chars=%s",
                context.context.correlation_id,
                context.context.actor_id,
                context.context.tenant_id,
                context.llm_config.model,
                context.llm_config.api_url,
                len(content or ""),
            )
            return ChatResponse(
                response=content or "Unable to parse response.",
                tool_calls=[],
                error_code="LLM_PARSE_ERROR",
            )
        set_span_attributes(span, {"chat.status": "ok"})
        return parsed
