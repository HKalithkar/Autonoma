from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.app.db import init_db, reset_db_cache, session_scope
from apps.api.app.main import create_app
from apps.api.app.models import Plugin


def _configure_db(tmp_path: Path) -> None:
    db_path = tmp_path / "test_secrets.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["DB_AUTO_CREATE"] = "true"
    os.environ["DB_SEED"] = "false"
    reset_db_cache()
    init_db()


def test_secret_resolve_via_api(monkeypatch, tmp_path: Path) -> None:
    _configure_db(tmp_path)
    os.environ["SERVICE_TOKEN"] = "token"

    def fake_post(url: str, json: dict[str, object], **kwargs):
        assert json["plugin"] == "vault-resolver"
        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {"result": {"secret": "resolved-secret"}}

        return FakeResponse()

    monkeypatch.setattr("apps.api.app.secrets.httpx.post", fake_post)

    client = TestClient(create_app())
    with session_scope() as session:
        session.add(
            Plugin(
                name="vault-resolver",
                version="v1",
                plugin_type="secret",
                endpoint="http://plugin-gateway:8002/invoke",
                actions={"resolve": {}},
                allowed_roles={},
                auth_type="bearer",
                auth_ref="secretkeyref:plugin:vault-resolver:token",
                auth_config={"header": "X-Vault-Token"},
                tenant_id="default",
            )
        )
        session.flush()

    response = client.post(
        "/v1/secrets/resolve",
        headers={"x-service-token": "token"},
        json={"ref": "secretkeyref:plugin:vault-resolver:kv/autonoma#token"},
    )
    assert response.status_code == 200
    assert response.json()["secret"] == "resolved-secret"
