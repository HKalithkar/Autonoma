from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from libs.common.context import get_request_context

from ..audit import audit_event
from ..chat_tools import ToolExecutor
from ..db import session_scope
from ..models import AgentConfig, ChatMessage, ChatSession, EventIngest
from ..rbac import require_permission

router = APIRouter(prefix="/v1/chat", tags=["chat"])
_LOGGER = logging.getLogger("autonoma.chat")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    response: str
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    error_code: str | None = None


def _agent_runtime_url() -> str:
    return os.getenv("AGENT_RUNTIME_URL", "http://agent-runtime:8001")


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _extract_explicit_workflow_name(message: str) -> str | None:
    patterns = [
        r"\bworkflow\s+([A-Za-z0-9_.:-]+)\b",
        r"\btrigger\s+workflow\s+([A-Za-z0-9_.:-]+)\b",
        r"\brun\s+workflow\s+([A-Za-z0-9_.:-]+)\b",
        r"\bexecute\s+workflow\s+([A-Za-z0-9_.:-]+)\b",
        r"\bstart\s+workflow\s+([A-Za-z0-9_.:-]+)\b",
        r"\b(?:run|trigger|execute|start)\s+([A-Za-z0-9_.:-]*[-_.:][A-Za-z0-9_.:-]*)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _names_match(requested: str | None, actual: str | None) -> bool:
    if not requested or not actual:
        return False
    return requested.strip().lower() == actual.strip().lower()


def _extract_environment(message: str) -> str | None:
    match = re.search(r"\b(prod|production|stage|staging|dev)\b", message, re.IGNORECASE)
    if not match:
        return None
    value = match.group(1).lower()
    if value == "production":
        return "prod"
    if value == "staging":
        return "stage"
    return value


def _format_workflow_run_example(
    workflow_name: str | None,
    fields: list[str] | None,
) -> str:
    cleaned_fields = [field for field in (fields or []) if field]
    workflow_part = f"workflow {workflow_name}" if workflow_name else "workflow <name>"
    if cleaned_fields:
        params = ", ".join(f"{field}: <value>" for field in cleaned_fields)
    else:
        params = "param: <value>"
    return f"Example: run {workflow_part} with {params}"


def _extract_params_from_message(message: str) -> dict[str, Any]:
    params: dict[str, Any] = {}
    def _unquote(raw: str) -> str:
        if raw.startswith('"') and raw.endswith('"'):
            value = raw[1:-1]
            return value.replace('\\"', '"').replace("\\\\", "\\")
        if raw.startswith("'") and raw.endswith("'"):
            value = raw[1:-1]
            return value.replace("\\'", "'").replace("\\\\", "\\")
        return raw

    def _trim_unquoted_value(raw: str) -> str:
        value = raw.strip()
        for token in [" and ", " with ", " in ", " on ", " for ", " to ", " from "]:
            index = value.lower().find(token)
            if index > 0:
                value = value[:index].strip()
                break
        return value

    quoted_pattern = r"(\"(?:\\\\.|[^\"\\\\])*\"|'(?:\\\\.|[^'\\\\])*')"
    value_pattern = rf"{quoted_pattern}|[A-Za-z0-9_.-]+"

    json_match = re.search(r"\{.*\}", message, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(0))
            if isinstance(parsed, dict):
                params.update({str(k).strip(): v for k, v in parsed.items() if str(k).strip()})
        except json.JSONDecodeError:
            pass
    for match in re.finditer(r"\"([^\"]+)\"\s+as\s+\"([^\"]+)\"", message, re.IGNORECASE):
        key = match.group(1).strip()
        value = match.group(2).strip()
        if key:
            params.setdefault(key, value)
    for match in re.finditer(rf"\b([A-Za-z0-9_.-]+)\s+as\s+({value_pattern})\b", message):
        key = match.group(1).strip()
        raw = match.group(2).strip()
        if key and raw:
            params.setdefault(key, _unquote(raw))
    for match in re.finditer(r"\b([A-Za-z0-9_.-]+)\s+as\s+([^,]+)", message):
        key = match.group(1).strip()
        raw = match.group(2).strip()
        if key and raw and key not in params:
            params.setdefault(key, _trim_unquoted_value(raw))
    for match in re.finditer(
        rf"\b([A-Za-z0-9_.-]+)\s*=\s*({value_pattern})",
        message,
    ):
        key = match.group(1).strip()
        raw = match.group(2).strip()
        if key:
            params.setdefault(key, _unquote(raw))
    for match in re.finditer(r"\b([A-Za-z0-9_.-]+)\s*=\s*([^,]+)", message):
        key = match.group(1).strip()
        raw = match.group(2).strip()
        if key and raw and key not in params:
            params.setdefault(key, _trim_unquoted_value(raw))
    for match in re.finditer(
        rf"\b([A-Za-z0-9_.-]+)\s*:\s*({value_pattern})",
        message,
    ):
        key = match.group(1).strip()
        raw = match.group(2).strip()
        if key:
            params.setdefault(key, _unquote(raw))
    for match in re.finditer(r"\b([A-Za-z0-9_.-]+)\s*:\s*([^,]+)", message):
        key = match.group(1).strip()
        raw = match.group(2).strip()
        if key and raw and key not in params:
            params.setdefault(key, _trim_unquoted_value(raw))
    return params


def _is_run_intent(message: str) -> bool:
    lowered = message.lower()
    if not re.search(r"\b(run|trigger|execute|start|deploy)\b", lowered):
        return False
    if _extract_explicit_workflow_name(message):
        return True
    return bool(re.search(r"\b(workflow|job|pipeline|deploy|deployment)\b", lowered))


def _load_llm_overrides(session, tenant_id: str) -> dict[str, dict[str, Any]]:
    configs = session.query(AgentConfig).filter_by(tenant_id=tenant_id).all()
    return {
        cfg.agent_type: {
            "api_url": cfg.api_url,
            "model": cfg.model,
            "api_key_ref": cfg.api_key_ref,
        }
        for cfg in configs
    }


@router.post("", response_model=ChatResponse)
def chat(request: ChatRequest, ctx=require_permission("chat:run")) -> ChatResponse:
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing message")

    with session_scope() as session:
        session_id = request.session_id
        chat_session: ChatSession | None = None
        if session_id:
            try:
                session_uuid = uuid.UUID(session_id)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid session id"
                ) from exc
            chat_session = session.get(ChatSession, session_uuid)
            if not chat_session or chat_session.actor_id != ctx.actor_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
                )
        else:
            chat_session = ChatSession(
                title=message[:120],
                actor_id=ctx.actor_id,
                tenant_id=ctx.tenant_id,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(chat_session)
            session.flush()
            session_id = str(chat_session.id)

        history_rows = (
            session.query(ChatMessage)
            .filter(ChatMessage.session_id == chat_session.id)
            .order_by(ChatMessage.created_at.asc())
            .limit(20)
            .all()
        )
        history = [{"role": row.role, "content": row.content} for row in history_rows]

        user_message = ChatMessage(
            session_id=chat_session.id,
            role="user",
            content=message,
            tool_calls={},
            tool_results={},
            created_at=datetime.now(timezone.utc),
        )
        session.add(user_message)
        session.flush()
        chat_session.updated_at = datetime.now(timezone.utc)

        llm_overrides = _load_llm_overrides(session, ctx.tenant_id)
        event = EventIngest(
            event_type="chat.run",
            severity="info",
            summary="Chat request processed.",
            source="chat",
            details={
                "actor_id": ctx.actor_id,
                "session_id": session_id,
                "message_hash": _hash_text(message),
                "message_chars": len(message),
            },
            environment=os.getenv("ENVIRONMENT", "dev"),
            status="processing",
            actions={
                "trail": [
                    {
                        "step": "chat_received",
                        "actor": ctx.actor_id,
                        "status": "received",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ],
                "tool_calls": [],
            },
            correlation_id=get_request_context().correlation_id,
            tenant_id=ctx.tenant_id,
        )
        session.add(event)
        session.flush()
        payload: dict[str, Any] = {}
        try:
            timeout = float(os.getenv("CHAT_AGENT_RUNTIME_TIMEOUT", "10.0"))
            response = httpx.post(
                f"{_agent_runtime_url()}/v1/chat/respond",
                json={
                    "message": message,
                    "history": history[-10:],
                    "context": {
                        "correlation_id": get_request_context().correlation_id,
                        "actor_id": ctx.actor_id,
                        "tenant_id": ctx.tenant_id,
                    },
                    "llm_overrides": llm_overrides,
                },
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            _LOGGER.warning(
                "agent_runtime_timeout correlation_id=%s actor_id=%s tenant_id=%s error=%s",
                get_request_context().correlation_id,
                ctx.actor_id,
                ctx.tenant_id,
                exc,
            )
            payload = {
                "response": "Chat unavailable.",
                "tool_calls": [],
                "error_code": "CHAT_AGENT_RUNTIME_TIMEOUT",
            }
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            _LOGGER.warning(
                "agent_runtime_unavailable correlation_id=%s actor_id=%s tenant_id=%s error=%s",
                get_request_context().correlation_id,
                ctx.actor_id,
                ctx.tenant_id,
                exc,
            )
            payload = {
                "response": "Chat unavailable.",
                "tool_calls": [],
                "error_code": "CHAT_AGENT_RUNTIME_UNAVAILABLE",
            }
        response_text = str(payload.get("response", "") or "")
        error_code = payload.get("error_code")
        if response_text.strip().lower().startswith("chat unavailable"):
            _LOGGER.warning(
                "agent_runtime_chat_unavailable correlation_id=%s actor_id=%s tenant_id=%s "
                "response=%s",
                get_request_context().correlation_id,
                ctx.actor_id,
                ctx.tenant_id,
                response_text[:160],
            )
            audit_event(
                "chat.unavailable",
                "deny",
                {
                    "actor_id": ctx.actor_id,
                    "reason": "agent_runtime",
                    "response": response_text[:160],
                },
                session=session,
            )
        tool_calls = payload.get("tool_calls", [])
        tool_results: list[dict[str, Any]] = []
        explicit_workflow = _extract_explicit_workflow_name(message)
        run_intent = _is_run_intent(message)
        extracted_params = _extract_params_from_message(message)
        extracted_env = _extract_environment(message)
        mismatch_notes: list[str] = []
        workflow_get_results: list[dict[str, Any]] = []
        ran_workflow = False
        trail = list(event.actions.get("trail", [])) if event.actions else []
        trail.append(
            {
                "step": "agent_runtime_response",
                "actor": "agent-runtime",
                "status": "ok",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        executor = ToolExecutor(session, ctx, llm_overrides)
        tool_call_entries: list[dict[str, Any]] = []
        for call in tool_calls:
            action = str(call.get("action", "")).strip()
            params = call.get("params", {}) or {}
            try:
                result: Any
                if action == "workflow.run" and not run_intent:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Workflow run requires explicit run intent.",
                    )
                if action in {"workflow.get", "workflow.run"}:
                    requested_name = explicit_workflow
                    call_name = str(params.get("workflow_name") or params.get("name") or "").strip()
                    if requested_name and call_name and not _names_match(requested_name, call_name):
                        mismatch_notes.append(
                            f"Workflow name mismatch: requested {requested_name}, "
                            f"but tool call targeted {call_name}. Please confirm the workflow name."
                        )
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail="Workflow name mismatch. Confirmation required.",
                        )
                if action == "workflow.list":
                    result = executor.workflow_list(params)
                elif action == "workflow.create":
                    result = executor.workflow_create(params)
                elif action == "workflow.get":
                    result = executor.workflow_get(params)
                    if isinstance(result, dict):
                        workflow_get_results.append(result)
                elif action == "workflow.delete":
                    result = executor.workflow_delete(params)
                elif action == "workflow.run":
                    result = executor.workflow_run(params)
                    ran_workflow = True
                elif action == "agent.plan":
                    result = executor.agent_plan(params)
                elif action == "plugin.list":
                    result = executor.plugin_list(params)
                elif action == "plugin.get":
                    result = executor.plugin_get(params)
                elif action == "plugin.create":
                    result = executor.plugin_create(params)
                elif action == "plugin.delete":
                    result = executor.plugin_delete(params)
                elif action == "audit.list":
                    result = executor.audit_list(params)
                elif action == "approvals.list":
                    result = executor.approvals_list(params)
                elif action == "runs.list":
                    result = executor.runs_list(params)
                elif action == "run.get":
                    result = executor.run_get(params)
                elif action == "events.list":
                    result = executor.events_list(params)
                elif action == "approval.get":
                    result = executor.approval_get(params)
                elif action == "approval.decision":
                    result = executor.approval_decision(params)
                else:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown action"
                    )
                tool_results.append({"action": action, "status": "ok", "result": result})
                tool_call_entries.append({"tool": "api", "action": action, "status": "ok"})
                trail.append(
                    {
                        "step": "tool_call",
                        "actor": "api",
                        "status": "ok",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "details": {"action": action},
                    }
                )
            except HTTPException as exc:
                tool_results.append(
                    {
                        "action": action,
                        "status": "error",
                        "detail": exc.detail,
                    }
                )
                tool_call_entries.append({"tool": "api", "action": action, "status": "error"})
                trail.append(
                    {
                        "step": "tool_call",
                        "actor": "api",
                        "status": "error",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "details": {"action": action, "error": exc.detail},
                    }
                )

        if (
            run_intent
            and not ran_workflow
            and explicit_workflow
            and extracted_params
            and not mismatch_notes
        ):
            try:
                workflow_info = executor.workflow_get({"workflow_name": explicit_workflow})
                if isinstance(workflow_info, dict):
                    required_fields = workflow_info.get("required_fields") or []
                    optional_fields = workflow_info.get("optional_fields") or []
                    allowed_fields = {
                        str(field).strip()
                        for field in (required_fields + optional_fields)
                        if str(field).strip()
                    }
                    run_params = (
                        {k: v for k, v in extracted_params.items() if k in allowed_fields}
                        if allowed_fields
                        else dict(extracted_params)
                    )
                    missing_required = [
                        str(field).strip()
                        for field in required_fields
                        if str(field).strip() and str(field).strip() not in run_params
                    ]
                    if missing_required:
                        missing_required_list = ", ".join(missing_required)
                        mismatch_notes.append(
                            "Missing required fields for workflow run: "
                            f"{missing_required_list}. Please provide these fields."
                        )
                        mismatch_notes.append(
                            _format_workflow_run_example(explicit_workflow, missing_required)
                        )
                    else:
                        auto_params = {
                            "workflow_name": explicit_workflow,
                            "environment": extracted_env or "dev",
                            "params": run_params,
                        }
                        auto_result = executor.workflow_run(auto_params)
                        tool_calls.append({"action": "workflow.run", "params": auto_params})
                        tool_results.append(
                            {"action": "workflow.run", "status": "ok", "result": auto_result}
                        )
                        tool_call_entries.append(
                            {"tool": "api", "action": "workflow.run", "status": "ok"}
                        )
                        trail.append(
                            {
                                "step": "tool_call",
                                "actor": "api",
                                "status": "ok",
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "details": {"action": "workflow.run", "auto": True},
                            }
                        )
                        ran_workflow = True
            except HTTPException as exc:
                if exc.status_code == status.HTTP_404_NOT_FOUND:
                    mismatch_notes.append(
                        f"Workflow {explicit_workflow} not found. Please confirm the exact name."
                    )
                else:
                    mismatch_notes.append(str(exc.detail))

        summary_lines: list[str] = []

        def _as_list(value: Any) -> list[dict[str, Any]]:
            return value if isinstance(value, list) else []

        def _as_dict(value: Any) -> dict[str, Any]:
            return value if isinstance(value, dict) else {}

        for item in tool_results:
            status_label = item.get("status")
            action = str(item.get("action") or "").strip()
            result = item.get("result")
            if status_label != "ok":
                if action == "workflow.get":
                    detail_raw = item.get("detail")
                    if isinstance(detail_raw, str) and detail_raw == "Workflow not found":
                        if explicit_workflow:
                            summary_lines.append(
                                f"Workflow '{explicit_workflow}' does not exist."
                            )
                        else:
                            summary_lines.append("Requested workflow does not exist.")
                    elif isinstance(detail_raw, str) and detail_raw:
                        summary_lines.append(detail_raw)
                if action == "workflow.run":
                    detail_raw = item.get("detail")
                    if isinstance(detail_raw, dict):
                        detail = detail_raw
                        missing = detail.get("missing_required") or []
                        required_fields = detail.get("required_fields") or []
                        optional_fields = detail.get("optional_fields") or []
                        required_list = (
                            ", ".join(str(field) for field in required_fields)
                            if isinstance(required_fields, list) and required_fields
                            else "none"
                        )
                        optional_list = (
                            ", ".join(str(field) for field in optional_fields)
                            if isinstance(optional_fields, list) and optional_fields
                            else "none"
                        )
                        missing_list = (
                            ", ".join(str(field) for field in missing)
                            if isinstance(missing, list) and missing
                            else None
                        )
                        if missing_list:
                            example_fields = (
                                [str(field) for field in missing if str(field)]
                                if isinstance(missing, list) and missing
                                else [
                                    str(field)
                                    for field in required_fields
                                    if isinstance(required_fields, list)
                                    and str(field)
                                ]
                            )
                            summary_lines.append(
                                "Missing required fields for workflow run: "
                                f"{missing_list}. Required: {required_list}. "
                                f"Optional: {optional_list}."
                            )
                            summary_lines.append(
                                _format_workflow_run_example(explicit_workflow, example_fields)
                            )
                        else:
                            summary_lines.append(
                                "Workflow run failed due to invalid params. "
                                f"Required: {required_list}. Optional: {optional_list}."
                            )
                    elif isinstance(detail_raw, str) and detail_raw:
                        summary_lines.append(detail_raw)
                continue
            if action == "workflow.list":
                names = [
                    str(entry.get("name") or entry.get("id") or "").strip()
                    for entry in _as_list(result)
                    if isinstance(entry, dict)
                ]
                names = [name for name in names if name]
                summary_lines.append(
                    f"Workflows: {', '.join(names)}" if names else "Workflows: none"
                )
            elif action == "workflow.create":
                record = _as_dict(result)
                name = str(record.get("name") or "").strip()
                workflow_id = str(record.get("id") or "").strip()
                summary_lines.append(
                    f"Workflow created: {name} ({workflow_id})"
                    if name or workflow_id
                    else "Workflow created."
                )
            elif action == "workflow.get":
                record = _as_dict(result)
                name = str(record.get("name") or "").strip()
                workflow_id = str(record.get("id") or "").strip()
                required_fields = record.get("required_fields") or []
                optional_fields = record.get("optional_fields") or []
                required_list = (
                    ", ".join(str(field) for field in required_fields)
                    if isinstance(required_fields, list) and required_fields
                    else "none"
                )
                optional_list = (
                    ", ".join(str(field) for field in optional_fields)
                    if isinstance(optional_fields, list) and optional_fields
                    else "none"
                )
                summary_lines.append(
                    "Workflow details: "
                    + " · ".join(
                        part
                        for part in [
                            f"{name} ({workflow_id})" if name or workflow_id else None,
                            f"required: {required_list}",
                            f"optional: {optional_list}",
                        ]
                        if part
                    )
                )
            elif action == "workflow.delete":
                record = _as_dict(result)
                workflow_id = str(record.get("workflow_id") or "").strip()
                summary_lines.append(
                    f"Workflow deleted: {workflow_id}" if workflow_id else "Workflow deleted."
                )
            elif action == "workflow.run":
                record = _as_dict(result)
                run_id = str(record.get("run_id") or "").strip()
                status_label = str(record.get("status") or "").strip()
                job_id = str(record.get("job_id") or "").strip()
                parts = [
                    f"Run {run_id}" if run_id else "Run submitted",
                    f"status {status_label}" if status_label else "",
                    f"job {job_id}" if job_id else "",
                ]
                summary_lines.append(" · ".join(part for part in parts if part))
            elif action == "agent.plan":
                record = _as_dict(result)
                plan_id = str(record.get("plan_id") or "").strip()
                summary_lines.append(
                    f"Plan created: {plan_id}" if plan_id else "Plan created."
                )
            elif action == "plugin.list":
                names = [
                    str(entry.get("name") or entry.get("id") or "").strip()
                    for entry in _as_list(result)
                    if isinstance(entry, dict)
                ]
                names = [name for name in names if name]
                summary_lines.append(
                    f"Plugins: {', '.join(names)}" if names else "Plugins: none"
                )
            elif action == "plugin.create":
                record = _as_dict(result)
                name = str(record.get("name") or "").strip()
                plugin_id = str(record.get("id") or "").strip()
                summary_lines.append(
                    f"Plugin registered: {name} ({plugin_id})"
                    if name or plugin_id
                    else "Plugin registered."
                )
            elif action == "plugin.get":
                record = _as_dict(result)
                name = str(record.get("name") or "").strip()
                plugin_id = str(record.get("id") or "").strip()
                plugin_type = str(record.get("plugin_type") or "").strip()
                endpoint = str(record.get("endpoint") or "").strip()
                auth_type = str(record.get("auth_type") or "").strip()
                auth_ref = str(record.get("auth_ref") or "").strip()
                actions = record.get("actions")
                action_names = []
                if isinstance(actions, dict):
                    action_names = [str(key) for key in actions.keys() if str(key).strip()]
                parts = [
                    f"Plugin {name}" if name else "Plugin detail",
                    f"id {plugin_id}" if plugin_id else "",
                    f"type {plugin_type}" if plugin_type else "",
                    f"endpoint {endpoint}" if endpoint else "",
                    f"auth {auth_type}" if auth_type else "",
                    f"auth_ref {auth_ref}" if auth_ref else "",
                    f"actions {', '.join(action_names)}" if action_names else "",
                ]
                summary_lines.append(" · ".join(part for part in parts if part))
            elif action == "plugin.delete":
                record = _as_dict(result)
                plugin_id = str(record.get("plugin_id") or "").strip()
                summary_lines.append(
                    f"Plugin deleted: {plugin_id}" if plugin_id else "Plugin deleted."
                )
            elif action == "audit.list":
                count = len(_as_list(result))
                summary_lines.append(f"Audit events: {count}")
            elif action == "approvals.list":
                approvals = _as_list(result)
                if not approvals:
                    summary_lines.append("Approvals: none")
                else:
                    for entry in approvals:
                        if not isinstance(entry, dict):
                            continue
                        approval_id = str(entry.get("id") or "").strip()
                        workflow_name = str(entry.get("workflow_name") or "").strip()
                        status_label = str(entry.get("status") or "").strip()
                        environment = str(entry.get("environment") or "").strip()
                        parts = [
                            f"Approval {approval_id}" if approval_id else "Approval",
                            f"workflow {workflow_name}" if workflow_name else "",
                            f"env {environment}" if environment else "",
                            f"status {status_label}" if status_label else "",
                        ]
                        summary_lines.append(" · ".join(part for part in parts if part))
            elif action == "approval.get":
                record = _as_dict(result)
                approval_id = str(record.get("id") or "").strip()
                workflow_name = str(record.get("workflow_name") or "").strip()
                status_label = str(record.get("status") or "").strip()
                run_status = str(record.get("run_status") or "").strip()
                environment = str(record.get("environment") or "").strip()
                parts = [
                    f"Approval {approval_id}" if approval_id else "Approval detail",
                    f"workflow {workflow_name}" if workflow_name else "",
                    f"env {environment}" if environment else "",
                    f"status {status_label}" if status_label else "",
                    f"run {run_status}" if run_status else "",
                ]
                summary_lines.append(" · ".join(part for part in parts if part))
            elif action == "approval.decision":
                record = _as_dict(result)
                approval_id = str(record.get("approval_id") or "").strip()
                decision = str(record.get("decision") or "").strip()
                status_label = str(record.get("status") or "").strip()
                workflow_name = str(record.get("workflow_name") or "").strip()
                environment = str(record.get("environment") or "").strip()
                run_id = str(record.get("workflow_run_id") or "").strip()
                run_status = str(record.get("run_status") or "").strip()
                job_id = str(record.get("job_id") or "").strip()
                parts = [
                    f"Approval {approval_id}" if approval_id else "Approval decision",
                    f"decision {decision}" if decision else "",
                    f"status {status_label}" if status_label else "",
                    f"workflow {workflow_name}" if workflow_name else "",
                    f"env {environment}" if environment else "",
                    f"run {run_id}" if run_id else "",
                    f"run status {run_status}" if run_status else "",
                    f"job {job_id}" if job_id else "",
                ]
                summary_lines.append(" · ".join(part for part in parts if part))
            elif action == "runs.list":
                runs = _as_list(result)
                summary_lines.append(f"Runs: {len(runs)}")
            elif action == "run.get":
                record = _as_dict(result)
                run_id = str(record.get("id") or "").strip()
                workflow_name = str(record.get("workflow_name") or "").strip()
                status_label = str(record.get("status") or "").strip()
                environment = str(record.get("environment") or "").strip()
                job_id = str(record.get("job_id") or "").strip()
                parts = [
                    f"Run {run_id}" if run_id else "Run detail",
                    f"workflow {workflow_name}" if workflow_name else "",
                    f"env {environment}" if environment else "",
                    f"status {status_label}" if status_label else "",
                    f"job {job_id}" if job_id else "",
                ]
                summary_lines.append(" · ".join(part for part in parts if part))
            elif action == "events.list":
                events = _as_list(result)
                summary_lines.append(f"Events: {len(events)}")

        if summary_lines:
            response_text = (
                response_text.rstrip()
                + ("\n\n" if response_text.strip() else "")
                + "\n".join(summary_lines)
            )
        if mismatch_notes:
            response_text = (
                response_text.rstrip()
                + ("\n\n" if response_text.strip() else "")
                + "\n".join(mismatch_notes)
            )

        assistant_message = ChatMessage(
            session_id=chat_session.id,
            role="assistant",
            content=response_text,
            tool_calls={"items": tool_calls},
            tool_results={"items": tool_results},
            created_at=datetime.now(timezone.utc),
        )
        session.add(assistant_message)
        session.flush()
        event.status = "completed_with_errors" if any(
            entry.get("status") == "error" for entry in tool_call_entries
        ) else "completed"
        event.actions = {
            "trail": trail,
            "tool_calls": tool_call_entries,
        }
        event.details = {
            **event.details,
            "tool_calls": len(tool_calls),
            **({"error_code": error_code} if error_code else {}),
        }

        audit_event(
            "chat.message",
            "allow",
            {"session_id": session_id, "tool_calls": len(tool_calls)},
            session=session,
        )

        return ChatResponse(
            session_id=session_id,
            response=response_text,
            tool_calls=tool_calls,
            tool_results=tool_results,
            error_code=error_code,
        )


@router.get("/health")
def chat_health(ctx=require_permission("chat:run")) -> dict[str, Any]:
    url = f"{_agent_runtime_url()}/healthz"
    try:
        response = httpx.get(url, timeout=3.0)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        _LOGGER.warning(
            "agent_runtime_health_unavailable correlation_id=%s actor_id=%s tenant_id=%s error=%s",
            get_request_context().correlation_id,
            ctx.actor_id,
            ctx.tenant_id,
            exc,
        )
        return {"status": "unavailable", "agent_runtime": {"status": "error"}}
    except ValueError as exc:
        _LOGGER.warning(
            "agent_runtime_health_invalid_json correlation_id=%s actor_id=%s tenant_id=%s error=%s",
            get_request_context().correlation_id,
            ctx.actor_id,
            ctx.tenant_id,
            exc,
        )
        return {"status": "unavailable", "agent_runtime": {"status": "error"}}
    return {"status": "ok", "agent_runtime": payload}


@router.get("/sessions")
def list_sessions(ctx=require_permission("chat:run")) -> list[dict[str, Any]]:
    with session_scope() as session:
        sessions = (
            session.query(ChatSession)
            .filter(ChatSession.actor_id == ctx.actor_id)
            .order_by(ChatSession.updated_at.desc())
            .limit(20)
            .all()
        )
        return [
            {
                "id": str(item.id),
                "title": item.title,
                "updated_at": item.updated_at.isoformat(),
            }
            for item in sessions
        ]


@router.get("/sessions/{session_id}/messages")
def list_messages(session_id: str, ctx=require_permission("chat:run")) -> list[dict[str, Any]]:
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid session id"
        ) from exc
    with session_scope() as session:
        chat_session = session.get(ChatSession, session_uuid)
        if not chat_session or chat_session.actor_id != ctx.actor_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
        messages = (
            session.query(ChatMessage)
            .filter(ChatMessage.session_id == chat_session.id)
            .order_by(ChatMessage.created_at.asc())
            .limit(50)
            .all()
        )
        return [
            {
                "id": str(item.id),
                "role": item.role,
                "content": item.content,
                "tool_calls": item.tool_calls,
                "tool_results": item.tool_results,
                "created_at": item.created_at.isoformat(),
            }
            for item in messages
        ]
