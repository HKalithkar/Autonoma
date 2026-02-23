from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.plugin_gateway.app import main

app = main.app


def _base_payload() -> dict[str, Any]:
    return {
        "plugin": "vault-resolver",
        "action": "resolve",
        "params": {"ref": "vault:token"},
        "context": {
            "correlation_id": "corr-1",
            "actor_id": "user-1",
            "tenant_id": "default",
        },
    }


def _policy_result(*, allow: bool, deny_reasons: list[str] | None = None) -> dict[str, Any]:
    return {
        "result": {
            "allow": allow,
            "deny_reasons": deny_reasons or [],
            "required_approvals": [],
        }
    }


def _response(
    *,
    method: str = "POST",
    url: str = "http://test",
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


def test_invoke_rejects_invalid_token(monkeypatch) -> None:
    monkeypatch.setenv("PLUGIN_GATEWAY_TOKEN", "valid-token")
    client = TestClient(app)
    response = client.post("/invoke", json=_base_payload(), headers={"x-service-token": "bad"})
    assert response.status_code == 401


def test_invoke_policy_denied(monkeypatch) -> None:
    monkeypatch.setenv("PLUGIN_GATEWAY_TOKEN", "valid-token")

    async def fake_request_with_retry(method: str, url: str, **kwargs: Any):
        assert url.endswith("/v1/data/autonoma/decision")
        return _response(
            url=url,
            json_data=_policy_result(allow=False, deny_reasons=["default_deny"]),
        )

    monkeypatch.setattr(main, "_request_with_retry", fake_request_with_retry)
    client = TestClient(app)
    response = client.post(
        "/invoke",
        json=_base_payload(),
        headers={"x-service-token": "valid-token"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["deny_reasons"] == ["default_deny"]


def test_request_with_retry_retries_transient_errors(monkeypatch) -> None:
    monkeypatch.setenv("PLUGIN_GATEWAY_HTTP_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("PLUGIN_GATEWAY_HTTP_RETRY_BACKOFF_SECONDS", "0")
    calls = {"count": 0}

    async def fake_request(self, method: str, url: str, **kwargs: Any):
        calls["count"] += 1
        if calls["count"] < 3:
            raise httpx.ConnectError("temporary", request=httpx.Request(method, url))
        return _response(method=method, url=url, json_data={"ok": True})

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    response = asyncio.run(
        main._request_with_retry(
            "POST",
            "http://policy:8181/v1/data/autonoma/decision",
            json={},
        )
    )
    assert response.status_code == 200
    assert calls["count"] == 3


def test_request_with_retry_does_not_retry_non_transient_status(monkeypatch) -> None:
    monkeypatch.setenv("PLUGIN_GATEWAY_HTTP_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("PLUGIN_GATEWAY_HTTP_RETRY_BACKOFF_SECONDS", "0")
    calls = {"count": 0}

    async def fake_request(self, method: str, url: str, **kwargs: Any):
        calls["count"] += 1
        return _response(method=method, url=url, status_code=401)

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(main._request_with_retry("GET", "http://api:8000/v1/plugins/internal/resolve"))
    assert calls["count"] == 1


def test_invoke_secret_resolve(monkeypatch) -> None:
    monkeypatch.setenv("PLUGIN_GATEWAY_TOKEN", "valid-token")
    monkeypatch.setenv("SECRET_STORE_MAP", json.dumps({"vault:token": "resolved"}))

    async def fake_request_with_retry(method: str, url: str, **kwargs: Any):
        return _response(url=url, json_data=_policy_result(allow=True))

    monkeypatch.setattr(main, "_request_with_retry", fake_request_with_retry)

    client = TestClient(app)
    response = client.post(
        "/invoke",
        json=_base_payload(),
        headers={"x-service-token": "valid-token"},
    )
    assert response.status_code == 200
    assert response.json()["result"]["secret"] == "resolved"


def test_invoke_vault_secret_resolve(monkeypatch) -> None:
    monkeypatch.setenv("PLUGIN_GATEWAY_TOKEN", "valid-token")
    monkeypatch.setenv("VAULT_TOKEN", "vault-token")

    async def fake_request_with_retry(method: str, url: str, **kwargs: Any):
        if url.endswith("/v1/data/autonoma/decision"):
            return _response(method=method, url=url, json_data=_policy_result(allow=True))
        assert url == "http://vault:8200/v1/kv/data/autonoma"
        return _response(
            method=method,
            url=url,
            json_data={"data": {"data": {"airflow": "vault-secret"}}},
        )

    monkeypatch.setattr(main, "_request_with_retry", fake_request_with_retry)

    payload = _base_payload()
    payload["params"] = {
        "path": "kv/autonoma#airflow",
        "ref": "secretkeyref:plugin:vault-resolver:kv/autonoma#airflow",
        "plugin": "vault-resolver",
        "auth_ref": "env:VAULT_TOKEN",
        "auth_config": {"provider": "vault", "addr": "http://vault:8200", "mount": "kv"},
    }

    client = TestClient(app)
    response = client.post(
        "/invoke",
        json=payload,
        headers={"x-service-token": "valid-token"},
    )
    assert response.status_code == 200
    assert response.json()["result"]["secret"] == "vault-secret"


@pytest.mark.skipif(
    os.getenv("VAULT_INTEGRATION_TESTS", "").lower() != "1",
    reason="Vault integration tests disabled (set VAULT_INTEGRATION_TESTS=1)",
)
def test_invoke_vault_secret_resolve_integration(monkeypatch) -> None:
    import time

    monkeypatch.setenv("PLUGIN_GATEWAY_TOKEN", "valid-token")
    monkeypatch.setenv("VAULT_TOKEN", os.getenv("VAULT_TOKEN", "autonoma-dev-token"))
    monkeypatch.setenv("VAULT_ADDR", os.getenv("VAULT_ADDR", "http://vault:8200"))

    vault_addr = os.environ["VAULT_ADDR"].rstrip("/")
    health_url = f"{vault_addr}/v1/sys/health"
    data_url = f"{vault_addr}/v1/kv/data/autonoma"
    token = os.environ["VAULT_TOKEN"]
    ready = False
    for _ in range(30):
        try:
            health = httpx.get(health_url, timeout=2.0)
        except httpx.HTTPError:
            health = None
        if health and health.status_code == 200:
            try:
                data_resp = httpx.get(
                    data_url,
                    headers={"X-Vault-Token": token},
                    timeout=2.0,
                )
            except httpx.HTTPError:
                data_resp = None
            if data_resp and data_resp.status_code == 200:
                ready = True
                break
        if health and health.status_code not in {200, 501, 503}:
            pytest.skip(f"Vault health check returned {health.status_code}")
        time.sleep(1)
    if not ready:
        pytest.skip("Vault not ready after waiting for seeded secrets")

    async def fake_request_with_retry(method: str, url: str, **kwargs: Any):
        if url.endswith("/v1/data/autonoma/decision"):
            return _response(method=method, url=url, json_data=_policy_result(allow=True))
        vault_payload = httpx.get(
            url,
            headers=kwargs.get("headers"),
            timeout=2.0,
        ).json()
        return _response(method=method, url=url, json_data=vault_payload)

    monkeypatch.setattr(main, "_request_with_retry", fake_request_with_retry)

    payload = _base_payload()
    payload["params"] = {
        "path": "kv/autonoma#airflow",
        "ref": "secretkeyref:plugin:vault-resolver:kv/autonoma#airflow",
        "plugin": "vault-resolver",
        "auth_ref": "env:VAULT_TOKEN",
        "auth_config": {"provider": "vault", "addr": os.environ["VAULT_ADDR"], "mount": "kv"},
    }

    client = TestClient(app)
    response = client.post(
        "/invoke",
        json=payload,
        headers={"x-service-token": "valid-token"},
    )
    assert response.status_code == 200
    assert response.json()["result"]["secret"] == "admin"


def test_invoke_secret_missing_ref(monkeypatch) -> None:
    monkeypatch.setenv("PLUGIN_GATEWAY_TOKEN", "valid-token")

    async def fake_request_with_retry(method: str, url: str, **kwargs: Any):
        return _response(url=url, json_data=_policy_result(allow=True))

    monkeypatch.setattr(main, "_request_with_retry", fake_request_with_retry)
    payload = _base_payload()
    payload["params"] = {}

    client = TestClient(app)
    response = client.post(
        "/invoke",
        json=payload,
        headers={"x-service-token": "valid-token"},
    )
    assert response.status_code == 400


def test_invoke_gitops_missing_workflow_run(monkeypatch) -> None:
    monkeypatch.setenv("PLUGIN_GATEWAY_TOKEN", "valid-token")

    async def fake_request_with_retry(method: str, url: str, **kwargs: Any):
        return _response(url=url, json_data=_policy_result(allow=True))

    monkeypatch.setattr(main, "_request_with_retry", fake_request_with_retry)
    payload = _base_payload()
    payload["plugin"] = "gitops"
    payload["action"] = "create_change"
    payload["params"] = {}

    client = TestClient(app)
    response = client.post(
        "/invoke",
        json=payload,
        headers={"x-service-token": "valid-token"},
    )
    assert response.status_code == 400


def test_invoke_missing_invoke_url(monkeypatch) -> None:
    monkeypatch.setenv("PLUGIN_GATEWAY_TOKEN", "valid-token")
    monkeypatch.setenv("SERVICE_TOKEN", "service-token")
    monkeypatch.setenv("API_URL", "http://api:8000")

    async def fake_request_with_retry(method: str, url: str, **kwargs: Any):
        if url.endswith("/v1/data/autonoma/decision"):
            return _response(method=method, url=url, json_data=_policy_result(allow=True))
        if url.endswith("/v1/plugins/internal/resolve"):
            return _response(
                method=method,
                url=url,
                json_data={
                    "name": "airflow",
                    "plugin_type": "workflow",
                    "endpoint": "http://plugin-gateway:8002/invoke",
                    "auth_type": "none",
                    "auth_ref": None,
                    "auth_config": {},
                },
            )
        return _response(
            method=method,
            url=url,
            json_data={"status": "submitted", "job_id": "job-1"},
        )

    monkeypatch.setattr(main, "_request_with_retry", fake_request_with_retry)
    payload = _base_payload()
    payload["plugin"] = "airflow"
    payload["action"] = "trigger_dag"

    client = TestClient(app)
    response = client.post(
        "/invoke",
        json=payload,
        headers={"x-service-token": "valid-token"},
    )
    assert response.status_code == 400


def test_invoke_workflow_forward(monkeypatch) -> None:
    monkeypatch.setenv("PLUGIN_GATEWAY_TOKEN", "valid-token")
    monkeypatch.setenv("SERVICE_TOKEN", "service-token")
    monkeypatch.setenv("API_URL", "http://api:8000")

    async def fake_request_with_retry(method: str, url: str, **kwargs: Any):
        if url.endswith("/v1/data/autonoma/decision"):
            return _response(method=method, url=url, json_data=_policy_result(allow=True))
        if url.endswith("/v1/plugins/internal/resolve"):
            return _response(
                method=method,
                url=url,
                json_data={
                    "name": "airflow",
                    "plugin_type": "workflow",
                    "endpoint": "http://plugin-gateway:8002/invoke",
                    "auth_type": "none",
                    "auth_ref": None,
                    "auth_config": {"invoke_url": "http://adapter:9004/invoke"},
                },
            )
        assert url == "http://adapter:9004/invoke"
        return _response(
            method=method,
            url=url,
            json_data={"status": "submitted", "job_id": "job-1"},
        )

    monkeypatch.setattr(main, "_request_with_retry", fake_request_with_retry)
    payload = _base_payload()
    payload["plugin"] = "airflow"
    payload["action"] = "trigger_dag"

    client = TestClient(app)
    response = client.post(
        "/invoke",
        json=payload,
        headers={"x-service-token": "valid-token"},
    )
    assert response.status_code == 200
    assert response.json()["job_id"] == "job-1"


def test_invoke_mcp_tools_list(monkeypatch) -> None:
    monkeypatch.setenv("PLUGIN_GATEWAY_TOKEN", "valid-token")
    monkeypatch.setenv("SERVICE_TOKEN", "service-token")
    monkeypatch.setenv("API_URL", "http://api:8000")

    async def fake_request_with_retry(method: str, url: str, **kwargs: Any):
        if url.endswith("/v1/data/autonoma/decision"):
            return _response(method=method, url=url, json_data=_policy_result(allow=True))
        if url.endswith("/v1/plugins/internal/resolve"):
            return _response(
                method=method,
                url=url,
                json_data={
                    "name": "mcp-test",
                    "plugin_type": "mcp",
                    "endpoint": "http://mcp:9000",
                    "auth_type": "none",
                    "auth_ref": None,
                    "auth_config": {},
                },
            )
        assert url == "http://mcp:9000"
        return _response(
            method=method,
            url=url,
            json_data={"result": {"tools": [{"name": "ping"}]}},
        )

    monkeypatch.setattr(main, "_request_with_retry", fake_request_with_retry)
    payload = _base_payload()
    payload["plugin"] = "mcp-test"
    payload["action"] = "tools/list"
    payload["params"] = {}

    client = TestClient(app)
    response = client.post(
        "/invoke",
        json=payload,
        headers={"x-service-token": "valid-token"},
    )
    assert response.status_code == 200
    assert response.json()["result"]["result"]["tools"][0]["name"] == "ping"


def test_gitops_webhook_forwards(monkeypatch) -> None:
    monkeypatch.setenv("GITOPS_WEBHOOK_TOKEN", "webhook-token")
    monkeypatch.setenv("GITOPS_WEBHOOK_URL", "http://api:8000/v1/gitops/webhook")
    payload = {"workflow_run_id": "run-1", "status": "success", "details": {"tenant_id": "t1"}}

    calls: list[dict[str, Any]] = []

    async def fake_request_with_retry(method: str, url: str, **kwargs: Any):
        calls.append({"url": url, "headers": kwargs.get("headers", {})})
        return _response(method=method, url=url, json_data={"status": "ok"})

    monkeypatch.setattr(main, "_request_with_retry", fake_request_with_retry)

    client = TestClient(app)
    response = client.post("/gitops/webhook", json=payload)
    assert response.status_code == 200
    assert calls[0]["headers"]["x-service-token"] == "webhook-token"
