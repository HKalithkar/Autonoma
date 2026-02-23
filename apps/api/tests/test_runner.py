from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import HTTPException

from apps.api.app.db import init_db, reset_db_cache, session_scope
from apps.api.app.models import Plugin, Workflow
from apps.api.app.runner import invoke_workflow_plugin, resolve_secret_refs
from libs.common.context import set_request_context


def _configure_db(tmp_path: Path) -> None:
    db_path = tmp_path / "test_runner.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["DB_AUTO_CREATE"] = "true"
    os.environ["DB_SEED"] = "false"
    reset_db_cache()
    init_db()


def test_resolve_secret_refs_env_and_plugin(monkeypatch, tmp_path: Path) -> None:
    _configure_db(tmp_path)
    os.environ["MY_TOKEN"] = "env-secret"

    def fake_resolve(session, ref: str, context: dict[str, str]) -> str:
        assert ref.startswith("secretkeyref:")
        return "plugin-secret"

    monkeypatch.setattr("apps.api.app.runner.resolve_secret_ref", fake_resolve)

    resolved, redacted = resolve_secret_refs(
        session=None,
        params={
            "token": "env:MY_TOKEN",
            "password": "secretkeyref:plugin:vault:kv/token",
            "note": "plain",
        },
        context={"correlation_id": "c1", "actor_id": "u1", "tenant_id": "t1"},
    )
    assert resolved["token"] == "env-secret"
    assert redacted["token"] == "[REDACTED]"
    assert resolved["password"] == "plugin-secret"
    assert redacted["password"] == "[REDACTED]"
    assert resolved["note"] == "plain"
    assert redacted["note"] == "plain"


def test_invoke_workflow_plugin_gitops(monkeypatch, tmp_path: Path) -> None:
    _configure_db(tmp_path)
    set_request_context("corr-1", "user-1", "default")

    def fake_post(url: str, **kwargs: Any):
        assert kwargs["json"]["plugin"] == "gitops"
        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, Any]:
                return {"status": "submitted", "job_id": "job-1", "callback_url": "http://cb"}

        return FakeResponse()

    monkeypatch.setattr("apps.api.app.runner.httpx.post", fake_post)

    with session_scope() as session:
        plugin = Plugin(
            name="gitops",
            version="v1",
            plugin_type="workflow",
            endpoint="http://plugin-gateway:8002/invoke",
            actions={"create_change": {}},
            allowed_roles={},
            auth_type="none",
            auth_ref=None,
            auth_config={},
            tenant_id="default",
        )
        session.add(plugin)
        session.flush()
        workflow = Workflow(
            name="change",
            description="GitOps change",
            plugin_id=plugin.id,
            action="create_change",
            created_by="user-1",
            tenant_id="default",
        )
        session.add(workflow)
        session.flush()

        result = invoke_workflow_plugin(
            session,
            workflow,
            {"token": "env:MY_TOKEN"},
            workflow_run_id="run-1",
        )
        assert result["gitops"]["callback_url"] == "http://cb"


def test_invoke_workflow_plugin_handles_gateway_error(
    monkeypatch, tmp_path: Path
) -> None:
    _configure_db(tmp_path)
    set_request_context("corr-2", "user-1", "default")

    def fake_post(url: str, **kwargs: Any):
        request = httpx.Request("POST", url)
        return httpx.Response(502, request=request, text="bad gateway")

    monkeypatch.setattr("apps.api.app.runner.httpx.post", fake_post)

    with session_scope() as session:
        plugin = Plugin(
            name="jenkins",
            version="v1",
            plugin_type="workflow",
            endpoint="http://plugin-gateway:8002/invoke",
            actions={"trigger_job": {}},
            allowed_roles={},
            auth_type="none",
            auth_ref=None,
            auth_config={},
            tenant_id="default",
        )
        session.add(plugin)
        session.flush()
        workflow = Workflow(
            name="build",
            description="Build job",
            plugin_id=plugin.id,
            action="trigger_job",
            created_by="user-1",
            tenant_id="default",
        )
        session.add(workflow)
        session.flush()

        with pytest.raises(HTTPException) as excinfo:
            invoke_workflow_plugin(session, workflow, {"branch": "main"})
        assert excinfo.value.status_code == 502
        assert "Plugin gateway unavailable" in str(excinfo.value.detail)
