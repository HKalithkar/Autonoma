import sys
from pathlib import Path

from fastapi.testclient import TestClient

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.main import app  # noqa: E402


def _base_payload() -> dict:
    return {
        "goal": "Trigger workflow to refresh caches",
        "environment": "dev",
        "tools": ["plugin_gateway.invoke"],
        "documents": [],
        "context": {
            "correlation_id": "test-correlation",
            "actor_id": "demo_user",
            "tenant_id": "default",
        },
        "llm_overrides": {},
    }


def test_plan_routes_to_v1_runtime(monkeypatch) -> None:
    monkeypatch.setenv("SERVICE_TOKEN", "svc-token")

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "run_id": "run-v1-123",
                "status": "running",
                "summary": "Run accepted and dispatched to orchestrator workers.",
            }

    def fake_post(url: str, *args, **kwargs):
        assert url.endswith("/v1/orchestrator/runs")
        assert kwargs["headers"]["x-service-token"] == "svc-token"
        payload = kwargs["json"]
        assert payload["intent"] == "Trigger workflow to refresh caches"
        assert payload["context"]["tenant_id"] == "default"
        return _Resp()

    monkeypatch.setattr("app.main.httpx.post", fake_post)
    client = TestClient(app)
    response = client.post("/v1/agent/plan", json=_base_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "planned"
    assert body["plan_id"] == "v1-run-run-v1-123"


def test_plan_requires_service_token(monkeypatch) -> None:
    monkeypatch.delenv("SERVICE_TOKEN", raising=False)
    client = TestClient(app)
    response = client.post("/v1/agent/plan", json=_base_payload())
    assert response.status_code == 500
    assert response.json()["detail"] == "Missing SERVICE_TOKEN"
