from apps.api.app.agent_eval import evaluate_agent_run


def test_agent_eval_requires_approval_for_prod() -> None:
    result = evaluate_agent_run(
        goal="Refresh caches safely",
        environment="prod",
        tools=["plugin_gateway.invoke"],
        documents=[],
    )
    assert result.verdict == "require_approval"


def test_agent_eval_denies_destructive_prod_goal() -> None:
    result = evaluate_agent_run(
        goal="Delete production clusters",
        environment="prod",
        tools=["plugin_gateway.invoke"],
        documents=[],
    )
    assert result.verdict == "deny"
