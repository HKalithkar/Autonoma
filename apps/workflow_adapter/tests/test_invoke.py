from __future__ import annotations

from typing import Any

import httpx
from fastapi.testclient import TestClient

from apps.workflow_adapter.app.main import app


def _payload(plugin: str, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "plugin": plugin,
        "action": action,
        "params": params or {},
        "context": {
            "correlation_id": "corr-1",
            "actor_id": "actor-1",
            "tenant_id": "default",
        },
    }


def _response(
    *,
    method: str = "POST",
    url: str,
    status_code: int = 200,
    json_data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        request=httpx.Request(method, url),
        json=json_data if json_data is not None else {},
        headers=headers,
    )


def test_airflow_trigger_uses_dag_id_from_action(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_post(self, url: str, **kwargs: Any):
        assert url != "http://api:8000/v1/secrets/resolve"
        calls.append({"url": url, "json": kwargs.get("json")})
        return _response(url=url, json_data={"dag_run_id": "run-1"})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    client = TestClient(app)
    response = client.post("/invoke", json=_payload("airflow", "trigger_dag:dummy_daily"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == "run-1"
    assert calls[0]["url"].endswith("/api/v1/dags/dummy_daily/dagRuns")


def test_airflow_trigger_resolves_secret_ref(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_post(self, url: str, **kwargs: Any):
        if url == "http://api:8000/v1/secrets/resolve":
            return _response(url=url, json_data={"secret": "vault-pass"})

        calls.append({"url": url, "auth": kwargs.get("auth")})
        return _response(url=url, json_data={"dag_run_id": "run-2"})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setenv(
        "AIRFLOW_PASSWORD_REF",
        "secretkeyref:plugin:vault-resolver:kv/autonoma#airflow",
    )
    monkeypatch.setenv("SERVICE_TOKEN", "service-token")

    client = TestClient(app)
    response = client.post("/invoke", json=_payload("airflow", "trigger_dag:dummy_daily"))
    assert response.status_code == 200
    assert calls[0]["auth"] == ("admin", "vault-pass")


def test_jenkins_trigger_job(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_post(self, url: str, **kwargs: Any):
        calls.append({"url": url, "params": kwargs.get("params")})
        return _response(url=url, headers={"location": "http://jenkins/queue/item/42/"})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    client = TestClient(app)
    response = client.post("/invoke", json=_payload("jenkins", "trigger_job:dummy-build"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == "42"
    assert calls[0]["url"].endswith("/job/dummy-build/build")


def test_airflow_missing_dag_id(monkeypatch) -> None:
    client = TestClient(app)
    response = client.post("/invoke", json=_payload("airflow", "trigger_dag"))
    assert response.status_code == 400


def test_n8n_trigger_workflow_posts_webhook_and_callback(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_post(self, url: str, **kwargs: Any):
        calls.append({"url": url, "json": kwargs.get("json")})
        if url.endswith("/runs/internal/status"):
            return _response(url=url, json_data={"status": "ok"})
        return _response(url=url, json_data={"status": "success", "result": "done"})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setenv("SERVICE_TOKEN", "service-token")
    monkeypatch.setenv("N8N_BASE_URL", "http://n8n:5678")
    monkeypatch.setenv(
        "WORKFLOW_STATUS_CALLBACK_URL",
        "http://api:8000/v1/runs/internal/status",
    )

    client = TestClient(app)
    response = client.post(
        "/invoke",
        json=_payload(
            "n8n",
            "trigger_workflow:autonoma-health-check",
            params={
                "service_name": "payments",
                "_autonoma": {"runtime_run_id": "run-123"},
            },
        ),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "running"
    assert payload["job_id"] == "run-123"
    assert calls[0]["url"] == "http://n8n:5678/webhook/autonoma-health-check"
    assert calls[1]["url"] == "http://api:8000/v1/runs/internal/status"
    assert calls[1]["json"]["status"] == "succeeded"


def test_n8n_trigger_missing_webhook_path() -> None:
    client = TestClient(app)
    response = client.post("/invoke", json=_payload("n8n", "trigger_workflow", params={}))
    assert response.status_code == 400
