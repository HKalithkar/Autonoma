from apps.api.app.routes import chat as chat_routes


def test_run_intent_requires_explicit_action() -> None:
    assert chat_routes._is_run_intent("give me an example kubernetes deployment") is False
    assert chat_routes._is_run_intent("run workflow jenkins-dummy-deploy") is True
    assert chat_routes._is_run_intent("trigger workflow foo") is True
    assert chat_routes._is_run_intent("run jenkins-dummy-backup") is True


def test_extract_explicit_workflow_name() -> None:
    assert chat_routes._extract_explicit_workflow_name("trigger deployment") is None
    assert chat_routes._extract_explicit_workflow_name("workflow jenkins-dummy-deploy") == (
        "jenkins-dummy-deploy"
    )
    assert chat_routes._extract_explicit_workflow_name("run workflow foo-bar") == "foo-bar"
    assert chat_routes._extract_explicit_workflow_name("run jenkins-dummy-backup") == (
        "jenkins-dummy-backup"
    )


def test_format_workflow_run_example() -> None:
    assert (
        chat_routes._format_workflow_run_example("jenkins-dummy-build", ["branch"])
        == "Example: run workflow jenkins-dummy-build with branch: <value>"
    )
