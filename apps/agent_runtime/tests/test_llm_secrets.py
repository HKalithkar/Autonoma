import os

import pytest

from apps.agent_runtime.app import llm as llm_module


def test_resolve_api_key_via_plugin_gateway(monkeypatch) -> None:
    os.environ["SERVICE_TOKEN"] = "token"
    os.environ["SECRET_RESOLVER_URL"] = "http://api:8000/v1/secrets/resolve"

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"secret": "resolved-secret"}

    def fake_post(*args, **kwargs):
        return _FakeResponse()

    monkeypatch.setattr(llm_module.httpx, "post", fake_post)
    secret = llm_module.resolve_api_key(
        "secretkeyref:plugin:vault-resolver:kv/autonoma#llm",
        correlation_id="corr-1",
        actor_id="service:agent",
        tenant_id="default",
    )
    assert secret == "resolved-secret"


def test_resolve_llm_config_rejects_invalid_api_key_ref() -> None:
    defaults = {
        "orchestrator": {
            "api_url": "http://llm",
            "model": "model-1",
            "api_key_ref": "vault:bad",
        }
    }
    with pytest.raises(llm_module.LLMResolutionError, match="invalid_api_key_ref"):
        llm_module.resolve_llm_config("orchestrator", defaults, None)
