from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

import httpx
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.runtime import Runtime
from pydantic import BaseModel, Field, ValidationError
from typing_extensions import TypedDict

from libs.common.llm_defaults import load_llm_defaults

from .llm import LLMConfig, LLMResolutionError, get_chat_model, resolve_llm_config
from .memory import MemoryRef, MemoryStore, get_memory_store
from .tracing import get_tracer, set_span_attributes, set_span_context
from .vector_store import VectorStoreError, build_records, get_vector_store


class RequestContext(BaseModel):
    correlation_id: str
    actor_id: str
    tenant_id: str = "default"


class AgentPlanRequest(BaseModel):
    goal: str
    environment: str = Field(default="dev", pattern="^(dev|stage|prod)$")
    tools: list[str] = Field(default_factory=list)
    documents: list[str] = Field(default_factory=list)
    execute_tools: bool = False
    llm_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    context: RequestContext


class PlanStep(BaseModel):
    step_id: str
    title: str
    description: str
    agent: str
    status: str = "planned"


class ToolCall(BaseModel):
    tool: str
    action: str
    params: dict[str, Any]


class AgentPlanResponse(BaseModel):
    plan_id: str
    status: str
    plan: list[PlanStep]
    tool_calls: list[ToolCall]
    memory_refs: list[MemoryRef]
    refusal_reason: str | None = None
    traces: list[dict[str, Any]] = Field(default_factory=list)


class PlanDraftStep(BaseModel):
    title: str
    description: str


class PlanDraft(BaseModel):
    steps: list[PlanDraftStep]
    tool_calls: list[ToolCall] = Field(default_factory=list)


_ALLOWED_TOOLS = {"plugin_gateway.invoke"}
_INJECTION_PATTERNS = (
    "ignore previous",
    "system prompt",
    "exfiltrate",
    "credential",
    "api key",
    "password",
    "bypass policy",
)

_PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"


class PlanState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    plan: list[PlanStep]
    tool_calls: list[ToolCall]
    refusal_reason: str | None
    context: dict[str, Any]


@dataclass
class PlanContext:
    llm_config: LLMConfig
    agent_type: str
    fake_response: str | None = None


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _select_agent(goal: str) -> str:
    lowered = goal.lower()
    if "incident" in lowered or "alert" in lowered:
        return "event_response"
    if "security" in lowered or "compliance" in lowered:
        return "security_guardian"
    return "orchestrator"


def _detect_prompt_injection(documents: list[str]) -> str | None:
    for doc in documents:
        lowered = doc.lower()
        for pattern in _INJECTION_PATTERNS:
            if pattern in lowered:
                return f"prompt_injection:{pattern}"
    return None


def _validate_tools(tools: list[str]) -> str | None:
    for tool in tools:
        if tool not in _ALLOWED_TOOLS:
            return f"tool_not_allowed:{tool}"
    return None


def _validate_tool_calls(tool_calls: list[ToolCall], allowed_tools: list[str]) -> str | None:
    if tool_calls and not allowed_tools:
        return "tool_calls_not_allowed"
    for call in tool_calls:
        if call.tool not in _ALLOWED_TOOLS:
            return f"tool_call_not_allowed:{call.tool}"
        if allowed_tools and call.tool not in allowed_tools:
            return f"tool_call_not_allowed:{call.tool}"
    return None


def _read_prompt(name: str) -> str:
    path = _PROMPT_DIR / name
    return path.read_text().strip()


def _build_messages(
    payload: AgentPlanRequest,
    agent_type: str,
    retrieved_memory: list[dict[str, Any]],
) -> list[AnyMessage]:
    system_prompt = _read_prompt("system.txt")
    agent_prompt = _read_prompt(f"{agent_type}.txt")
    plan_prompt = _read_prompt("plan.txt")
    user_payload = {
        "goal": payload.goal,
        "environment": payload.environment,
        "allowed_tools": payload.tools,
        "documents": payload.documents,
        "retrieved_memory": retrieved_memory,
    }
    return [
        SystemMessage(content=system_prompt),
        SystemMessage(content=agent_prompt),
        SystemMessage(content=plan_prompt),
        HumanMessage(content=json.dumps(user_payload)),
    ]


def _retrieve_memory(
    goal: str, tenant_id: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    traces: list[dict[str, Any]] = []
    tracer = get_tracer()
    with tracer.start_as_current_span("planner.memory.retrieve") as span:
        set_span_attributes(
            span,
            {
                "memory.goal_chars": len(goal),
                "memory.tenant_id": tenant_id,
            },
        )
        try:
            vector_store = get_vector_store()
            top_k = int(os.getenv("MEMORY_SEARCH_TOP_K", "3"))
            results = vector_store.query(tenant_id, goal, top_k, {"type": "plan"})
            trimmed = [
                {
                    "id": item.id,
                    "score": item.score,
                    "text": item.text,
                    "metadata": item.metadata,
                }
                for item in results
            ]
            traces.append(
                {
                    "event": "memory.vector.search",
                    "timestamp": _utcnow(),
                    "result_count": len(trimmed),
                }
            )
            set_span_attributes(
                span,
                {
                    "memory.top_k": top_k,
                    "memory.result_count": len(trimmed),
                    "memory.status": "ok",
                },
            )
            return trimmed, traces
        except Exception:
            traces.append(
                {
                    "event": "memory.vector.search.failed",
                    "timestamp": _utcnow(),
                }
            )
            set_span_attributes(
                span,
                {
                    "memory.top_k": int(os.getenv("MEMORY_SEARCH_TOP_K", "3")),
                    "memory.result_count": 0,
                    "memory.status": "error",
                },
            )
            return [], traces


def _fake_plan_payload(goal: str, allowed_tools: list[str]) -> str:
    tool_calls = []
    if "workflow" in goal.lower() and "plugin_gateway.invoke" in allowed_tools:
        tool_calls = [
            {
                "tool": "plugin_gateway.invoke",
                "action": "trigger_dag",
                "params": {"dag_id": "autonoma-plan"},
            }
        ]
    payload = {
        "steps": [
            {
                "title": "Analyze goal",
                "description": f"Summarize the objective: {goal}",
            },
            {
                "title": "Select workflow",
                "description": "Pick the safest workflow or remediation path.",
            },
            {
                "title": "Execute via plugin gateway",
                "description": "Invoke the selected action through approved tooling.",
            },
        ],
        "tool_calls": tool_calls,
    }
    return json.dumps(payload)


def _parse_plan_response(raw: str) -> PlanDraft:
    return PlanDraft.model_validate_json(raw)


def _plan_node(state: PlanState, runtime: Runtime[PlanContext]) -> dict[str, Any]:
    try:
        llm = get_chat_model(
            runtime.context.llm_config,
            correlation_id=state["context"]["correlation_id"],
            actor_id=state["context"]["actor_id"],
            tenant_id=state["context"]["tenant_id"],
            fake_response=runtime.context.fake_response,
        )
        response = llm.invoke(state["messages"])
        content = getattr(response, "content", "")
    except LLMResolutionError as exc:
        return {
            "plan": [],
            "tool_calls": [],
            "refusal_reason": str(exc),
        }
    except Exception:
        return {
            "plan": [],
            "tool_calls": [],
            "refusal_reason": "llm_unavailable",
        }
    try:
        draft = _parse_plan_response(content)
    except ValidationError:
        return {
            "messages": [AIMessage(content=content)],
            "plan": [],
            "tool_calls": [],
            "refusal_reason": "llm_parse_error",
        }
    steps: list[PlanStep] = []
    for idx, step in enumerate(draft.steps, start=1):
        steps.append(
            PlanStep(
                step_id=f"step-{idx}",
                title=step.title,
                description=step.description,
                agent=runtime.context.agent_type,
            )
        )
    return {
        "messages": [AIMessage(content=content)],
        "plan": steps,
        "tool_calls": draft.tool_calls,
        "refusal_reason": None,
    }


def _build_graph() -> Any:
    builder = StateGraph(PlanState, context_schema=PlanContext)
    builder.add_node("plan", _plan_node)
    builder.add_edge(START, "plan")
    builder.add_edge("plan", END)
    return builder.compile()


_PLAN_GRAPH = _build_graph()


def generate_plan(payload: AgentPlanRequest) -> AgentPlanResponse:
    memory: MemoryStore = get_memory_store()
    agent_type = _select_agent(payload.goal)
    defaults = load_llm_defaults()
    plan_id = str(uuid.uuid4())
    tracer = get_tracer()

    traces: list[dict[str, Any]] = [
        {
            "event": "plan.requested",
            "timestamp": _utcnow(),
            "agent": agent_type,
            "environment": payload.environment,
            "correlation_id": payload.context.correlation_id,
        }
    ]

    with tracer.start_as_current_span("planner.generate") as span:
        set_span_context(
            span,
            correlation_id=payload.context.correlation_id,
            actor_id=payload.context.actor_id,
            tenant_id=payload.context.tenant_id,
        )
        set_span_attributes(
            span,
            {
                "planner.plan_id": plan_id,
                "planner.agent_type": agent_type,
                "planner.environment": payload.environment,
                "planner.goal_chars": len(payload.goal),
                "planner.tools_requested": len(payload.tools),
            },
        )

        injection_reason = _detect_prompt_injection(payload.documents)
        if injection_reason:
            traces.append(
                {
                    "event": "plan.refused",
                    "timestamp": _utcnow(),
                    "reason": injection_reason,
                }
            )
            set_span_attributes(
                span,
                {
                    "planner.status": "refused",
                    "planner.refusal_reason": injection_reason,
                },
            )
            return AgentPlanResponse(
                plan_id=plan_id,
                status="refused",
                plan=[],
                tool_calls=[],
                memory_refs=[],
                refusal_reason=injection_reason,
                traces=traces,
            )

        tool_issue = _validate_tools(payload.tools)
        if tool_issue:
            traces.append(
                {
                    "event": "plan.refused",
                    "timestamp": _utcnow(),
                    "reason": tool_issue,
                }
            )
            set_span_attributes(
                span,
                {
                    "planner.status": "refused",
                    "planner.refusal_reason": tool_issue,
                },
            )
            return AgentPlanResponse(
                plan_id=plan_id,
                status="refused",
                plan=[],
                tool_calls=[],
                memory_refs=[],
                refusal_reason=tool_issue,
                traces=traces,
            )

        try:
            llm_config = resolve_llm_config(agent_type, defaults, payload.llm_overrides)
        except LLMResolutionError as exc:
            reason = str(exc)
            traces.append(
                {
                    "event": "plan.refused",
                    "timestamp": _utcnow(),
                    "reason": reason,
                }
            )
            set_span_attributes(
                span,
                {
                    "planner.status": "refused",
                    "planner.refusal_reason": reason,
                },
            )
            return AgentPlanResponse(
                plan_id=plan_id,
                status="refused",
                plan=[],
                tool_calls=[],
                memory_refs=[],
                refusal_reason=reason,
                traces=traces,
            )

        retrieved_memory, memory_traces = _retrieve_memory(
            payload.goal, payload.context.tenant_id
        )
        traces.extend(memory_traces)

        messages = _build_messages(payload, agent_type, retrieved_memory)
        fake_response = None
        if os.getenv("AUTONOMA_FAKE_LLM") == "1":
            fake_response = _fake_plan_payload(payload.goal, payload.tools)
        state = _PLAN_GRAPH.invoke(
            {
                "messages": messages,
                "plan": [],
                "tool_calls": [],
                "refusal_reason": None,
                "context": payload.context.model_dump(),
            },
            context=PlanContext(
                llm_config=llm_config,
                agent_type=agent_type,
                fake_response=fake_response,
            ),
            config={"recursion_limit": 5},
        )
        plan_steps = state.get("plan", [])
        tool_calls = state.get("tool_calls", [])
        refusal_reason = state.get("refusal_reason")
        if refusal_reason:
            traces.append(
                {
                    "event": "plan.refused",
                    "timestamp": _utcnow(),
                    "reason": refusal_reason,
                }
            )
            set_span_attributes(
                span,
                {
                    "planner.status": "refused",
                    "planner.refusal_reason": refusal_reason,
                },
            )
            return AgentPlanResponse(
                plan_id=plan_id,
                status="refused",
                plan=[],
                tool_calls=[],
                memory_refs=[],
                refusal_reason=refusal_reason,
                traces=traces,
            )

        if not plan_steps:
            traces.append(
                {
                    "event": "plan.refused",
                    "timestamp": _utcnow(),
                    "reason": "llm_empty_plan",
                }
            )
            set_span_attributes(
                span,
                {
                    "planner.status": "refused",
                    "planner.refusal_reason": "llm_empty_plan",
                },
            )
            return AgentPlanResponse(
                plan_id=plan_id,
                status="refused",
                plan=[],
                tool_calls=[],
                memory_refs=[],
                refusal_reason="llm_empty_plan",
                traces=traces,
            )

        tool_call_issue = _validate_tool_calls(tool_calls, payload.tools)
        if tool_call_issue:
            traces.append(
                {
                    "event": "plan.refused",
                    "timestamp": _utcnow(),
                    "reason": tool_call_issue,
                }
            )
            set_span_attributes(
                span,
                {
                    "planner.status": "refused",
                    "planner.refusal_reason": tool_call_issue,
                },
            )
            return AgentPlanResponse(
                plan_id=plan_id,
                status="refused",
                plan=[],
                tool_calls=[],
                memory_refs=[],
                refusal_reason=tool_call_issue,
                traces=traces,
            )
        traces.append(
            {
                "event": "plan.llm.configured",
                "timestamp": _utcnow(),
                "agent": agent_type,
                "model": llm_config.model,
                "api_url": llm_config.api_url,
            }
        )

        memory_refs = [
            MemoryRef(
                ref_type="vector",
                ref_uri=f"vector://memory/{plan_id}",
                metadata={"agent": agent_type, "model": llm_config.model},
            ),
            MemoryRef(
                ref_type="timeseries",
                ref_uri=f"timeseries://metrics/{plan_id}",
                metadata={"agent": agent_type, "environment": payload.environment},
            ),
        ]

        vector_refs: list[MemoryRef] = []
        try:
            vector_store = get_vector_store()
            texts: list[str] = []
            if payload.documents:
                texts.extend(payload.documents)
            summary = " | ".join([step.title for step in plan_steps])
            texts.append(f"goal: {payload.goal}")
            texts.append(f"plan: {summary}")
            records = build_records(
                tenant_id=payload.context.tenant_id,
                texts=texts,
                metadata={
                    "type": "plan",
                    "source": "agent-runtime",
                    "correlation_id": payload.context.correlation_id,
                    "agent_type": agent_type,
                    "plan_id": plan_id,
                },
            )
            ids = vector_store.upsert_texts(payload.context.tenant_id, records)
            vector_refs = [
                MemoryRef(
                    ref_type="vector",
                    ref_uri=f"vector://{os.getenv('VECTOR_STORE_PROVIDER', 'weaviate')}/{item_id}",
                    metadata={"agent": agent_type, "plan_id": plan_id},
                )
                for item_id in ids
            ]
        except (VectorStoreError, httpx.RequestError, Exception):
            traces.append(
                {
                    "event": "memory.vector.failed",
                    "timestamp": _utcnow(),
                    "agent": agent_type,
                }
            )

        memory_refs.extend(vector_refs)

        memory.store_short_term(
            payload.context.correlation_id,
            {
                "plan_id": plan_id,
                "agent": agent_type,
                "goal": payload.goal,
                "steps": [step.model_dump() for step in plan_steps],
            },
        )
        memory.store_long_term(payload.context.tenant_id, memory_refs)

        traces.append(
            {
                "event": "plan.created",
                "timestamp": _utcnow(),
                "plan_id": plan_id,
                "agent": agent_type,
                "tool_calls": [call.model_dump() for call in tool_calls],
            }
        )
        set_span_attributes(
            span,
            {
                "planner.status": "planned",
                "planner.plan_steps": len(plan_steps),
                "planner.tool_calls.count": len(tool_calls),
                "planner.tool_calls.names": ",".join(
                    sorted({call.tool for call in tool_calls})
                ),
            },
        )

        return AgentPlanResponse(
            plan_id=plan_id,
            status="planned",
            plan=plan_steps,
            tool_calls=tool_calls,
            memory_refs=memory_refs,
            traces=traces,
        )
