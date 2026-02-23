import os
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.app.db import init_db, reset_db_cache
from apps.api.app.main import create_app
from apps.api.app.models import WorkflowRun


def _configure_db(tmp_path: Path) -> None:
    db_path = tmp_path / "test_gitops.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["DB_AUTO_CREATE"] = "true"
    os.environ["DB_SEED"] = "false"
    reset_db_cache()
    init_db()


def test_gitops_webhook_updates_run(tmp_path: Path) -> None:
    _configure_db(tmp_path)
    os.environ["SERVICE_TOKEN"] = "token"
    client = TestClient(create_app())

    # Insert a workflow run
    from apps.api.app.db import session_scope

    with session_scope() as session:
        run = WorkflowRun(
            workflow_id=uuid.uuid4(),
            status="submitted",
            environment="dev",
        )
        session.add(run)
        session.flush()
        run_id = str(run.id)

    def fake_post(*args, **kwargs):
        class _Resp:
            def raise_for_status(self) -> None:
                return None

        return _Resp()

    import apps.api.app.routes.gitops as gitops_module

    def fake_audit(*args, **kwargs):
        return None

    import apps.api.app.audit as audit_module

    audit_module.audit_event = fake_audit
    gitops_module.httpx.post = fake_post

    response = client.post(
        "/v1/gitops/webhook",
        headers={"x-service-token": "token"},
        json={
            "workflow_run_id": run_id,
            "status": "failed",
            "commit_sha": "abc123",
            "pipeline_id": "pipe-1",
        },
    )
    assert response.status_code == 200
    with session_scope() as session:
        updated = session.query(WorkflowRun).filter_by(id=uuid.UUID(run_id)).one()
        assert updated.status == "failed"
