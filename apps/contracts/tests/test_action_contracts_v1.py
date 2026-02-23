from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

SCHEMA_DIR = Path(__file__).resolve().parents[3] / "contracts" / "action" / "v1"


def schema_dict(schema_filename: str) -> dict:
    schema_path = SCHEMA_DIR / schema_filename
    return json.loads(schema_path.read_text(encoding="utf-8"))


def validate_payload(schema_filename: str, payload: dict) -> None:
    validator = Draft202012Validator(
        schema_dict(schema_filename), format_checker=FormatChecker()
    )
    validator.validate(payload)


def base_actor() -> dict:
    return {
        "type": "agent",
        "id": "agent-123",
        "display_name": "Planner",
    }


def action_request_payload() -> dict:
    return {
        "correlation_id": "11111111-1111-1111-1111-111111111111",
        "created_at": "2026-02-01T12:00:00Z",
        "actor": base_actor(),
        "idempotency_key": "req-001",
        "intent": "trigger workflow",
        "target": {
            "type": "workflow",
            "id": "wf-123",
            "display_name": "Nightly ETL",
            "uri": "workflow://wf-123",
        },
        "parameters": {"dry_run": False},
        "environment": "dev",
        "tool": {"type": "plugin", "name": "airflow", "action": "trigger"},
        "metadata": {"source": "unit-test"},
    }


def action_plan_payload() -> dict:
    return {
        "correlation_id": "22222222-2222-2222-2222-222222222222",
        "created_at": "2026-02-01T12:01:00Z",
        "actor": base_actor(),
        "plan_id": "plan-1",
        "summary": "Execute two steps",
        "steps": [
            {
                "step_id": "step-1",
                "order": 1,
                "depends_on": [],
                "action": {
                    "idempotency_key": "step-1-req",
                    "intent": "trigger workflow",
                    "target": {"type": "workflow", "id": "wf-123"},
                    "parameters": {"dry_run": True},
                    "environment": "dev",
                    "tool": {"type": "plugin", "name": "airflow"},
                    "metadata": {"trace": "unit"},
                },
            }
        ],
    }


def policy_decision_payload() -> dict:
    return {
        "correlation_id": "33333333-3333-3333-3333-333333333333",
        "created_at": "2026-02-01T12:02:00Z",
        "actor": base_actor(),
        "decision_id": "pol-1",
        "decision": "allow",
        "reasons": ["policy allows dev workflow"],
        "risk_level": "low",
        "evaluated_at": "2026-02-01T12:02:01Z",
        "policy_id": "policy-1",
        "metadata": {"rule": "allow-dev"},
    }


def approval_request_payload() -> dict:
    return {
        "correlation_id": "44444444-4444-4444-4444-444444444444",
        "created_at": "2026-02-01T12:03:00Z",
        "actor": base_actor(),
        "approval_request_id": "apr-1",
        "action_request_id": "req-001",
        "policy_decision_id": "pol-2",
        "approver_roles": ["ops-admin"],
        "status": "pending",
        "expires_at": "2026-02-02T12:03:00Z",
        "comments": "Needs approval",
        "metadata": {"ticket": "CHG-1"},
    }


def approval_decision_payload() -> dict:
    return {
        "correlation_id": "55555555-5555-5555-5555-555555555555",
        "created_at": "2026-02-01T12:04:00Z",
        "actor": base_actor(),
        "approval_decision_id": "apd-1",
        "approval_request_id": "apr-1",
        "status": "approved",
        "decided_by": {
            "type": "user",
            "id": "user-1",
            "display_name": "Ops Lead",
        },
        "decided_at": "2026-02-01T12:04:30Z",
        "comments": "Looks good",
        "reason": "Within policy",
        "metadata": {"ticket": "CHG-1"},
    }


def action_execution_result_payload() -> dict:
    return {
        "correlation_id": "66666666-6666-6666-6666-666666666666",
        "created_at": "2026-02-01T12:05:00Z",
        "actor": base_actor(),
        "idempotency_key": "exec-001",
        "action_execution_id": "exe-1",
        "action_request_id": "req-001",
        "status": "succeeded",
        "outputs": {"run_id": "run-123"},
        "timing": {
            "started_at": "2026-02-01T12:05:00Z",
            "finished_at": "2026-02-01T12:05:30Z",
            "duration_ms": 30000,
        },
        "metadata": {"source": "unit-test"},
    }


def audit_event_payload_execution() -> dict:
    return {
        "correlation_id": "77777777-7777-7777-7777-777777777777",
        "created_at": "2026-02-01T12:06:00Z",
        "actor": base_actor(),
        "idempotency_key": "exec-001",
        "event_id": "evt-1",
        "event_type": "action.execution.succeeded",
        "event_category": "execution",
        "occurred_at": "2026-02-01T12:05:30Z",
        "entity": {"type": "action_execution", "id": "exe-1"},
        "payload_summary": {
            "summary": "Action execution succeeded",
            "attributes": {"action_request_id": "req-001"},
        },
        "redacted_fields": [],
        "metadata": {"source": "unit-test"},
    }


def audit_event_payload_non_execution() -> dict:
    return {
        "correlation_id": "88888888-8888-8888-8888-888888888888",
        "created_at": "2026-02-01T12:07:00Z",
        "actor": base_actor(),
        "event_id": "evt-2",
        "event_type": "policy.decision.allow",
        "event_category": "policy",
        "occurred_at": "2026-02-01T12:07:00Z",
        "entity": {"type": "policy_decision", "id": "pol-1"},
        "payload_summary": {"summary": "Policy allow"},
        "redacted_fields": [],
        "metadata": {"source": "unit-test"},
    }


SCHEMAS = {
    "action_request.schema.json": action_request_payload,
    "action_plan.schema.json": action_plan_payload,
    "policy_decision.schema.json": policy_decision_payload,
    "approval_request.schema.json": approval_request_payload,
    "approval_decision.schema.json": approval_decision_payload,
    "action_execution_result.schema.json": action_execution_result_payload,
    "audit_event.schema.json": audit_event_payload_execution,
}


@pytest.mark.parametrize("schema_filename,payload_factory", SCHEMAS.items())
def test_valid_payloads(schema_filename: str, payload_factory) -> None:
    validate_payload(schema_filename, payload_factory())


@pytest.mark.parametrize("schema_filename,payload_factory", SCHEMAS.items())
def test_missing_correlation_id_fails(schema_filename: str, payload_factory) -> None:
    payload = payload_factory()
    payload.pop("correlation_id")
    with pytest.raises(ValidationError):
        validate_payload(schema_filename, payload)


@pytest.mark.parametrize(
    "schema_filename,payload_factory",
    [
        ("action_request.schema.json", action_request_payload),
        ("action_execution_result.schema.json", action_execution_result_payload),
    ],
)
def test_missing_idempotency_key_fails(schema_filename: str, payload_factory) -> None:
    payload = payload_factory()
    payload.pop("idempotency_key")
    with pytest.raises(ValidationError):
        validate_payload(schema_filename, payload)


def test_audit_event_execution_requires_idempotency_key() -> None:
    payload = audit_event_payload_execution()
    payload.pop("idempotency_key")
    with pytest.raises(ValidationError):
        validate_payload("audit_event.schema.json", payload)


def test_audit_event_non_execution_allows_missing_idempotency_key() -> None:
    validate_payload("audit_event.schema.json", audit_event_payload_non_execution())


@pytest.mark.parametrize("schema_filename,payload_factory", SCHEMAS.items())
def test_unknown_fields_rejected(schema_filename: str, payload_factory) -> None:
    payload = payload_factory()
    payload["unknown"] = "nope"
    with pytest.raises(ValidationError):
        validate_payload(schema_filename, payload)
