import os

from fastapi.testclient import TestClient

from apps.agent_runtime.app.main import app


def test_chat_respond_with_fake_llm() -> None:
    os.environ["AUTONOMA_FAKE_LLM"] = "1"
    client = TestClient(app)
    response = client.post(
        "/v1/chat/respond",
        json={
            "message": "List workflows",
            "history": [],
            "context": {
                "correlation_id": "corr-1",
                "actor_id": "user-1",
                "tenant_id": "default",
            },
            "fake_response": '{"response": "Here are workflows", "tool_calls": []}',
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["response"] == "Here are workflows"
    assert payload["tool_calls"] == []
    os.environ.pop("AUTONOMA_FAKE_LLM", None)


def test_chat_respond_with_invalid_json_sets_error_code() -> None:
    os.environ["AUTONOMA_FAKE_LLM"] = "1"
    client = TestClient(app)
    response = client.post(
        "/v1/chat/respond",
        json={
            "message": "List workflows",
            "history": [],
            "context": {
                "correlation_id": "corr-1",
                "actor_id": "user-1",
                "tenant_id": "default",
            },
            "fake_response": "not-json",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["error_code"] == "LLM_PARSE_ERROR"
    os.environ.pop("AUTONOMA_FAKE_LLM", None)


def test_chat_respond_missing_context_fields_returns_422() -> None:
    client = TestClient(app)
    response = client.post(
        "/v1/chat/respond",
        json={
            "message": "List workflows",
            "history": [],
            "context": {"tenant_id": "default"},
        },
    )
    assert response.status_code == 422
