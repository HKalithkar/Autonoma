from __future__ import annotations

import os
from typing import Any

from sqlalchemy.exc import OperationalError, ProgrammingError

from .db import session_scope
from .models import Plugin, Workflow


def _get_or_create_plugin(
    session,
    *,
    name: str,
    version: str,
    plugin_type: str,
    endpoint: str,
    actions: dict[str, dict[str, str]],
    allowed_roles: dict[str, list[str]],
    auth_type: str,
    auth_ref: str | None,
    auth_config: dict[str, str],
    tenant_id: str,
) -> Plugin:
    plugin = session.query(Plugin).filter(Plugin.name == name).first()
    if plugin:
        if auth_config.get("invoke_url") and not plugin.auth_config.get("invoke_url"):
            plugin.auth_config = {**plugin.auth_config, **auth_config}
        if actions and not plugin.actions:
            plugin.actions = actions
        if auth_ref and not plugin.auth_ref:
            plugin.auth_ref = auth_ref
        return plugin
    plugin = Plugin(
        name=name,
        version=version,
        plugin_type=plugin_type,
        endpoint=endpoint,
        actions=actions,
        allowed_roles=allowed_roles,
        auth_type=auth_type,
        auth_ref=auth_ref,
        auth_config=auth_config,
        tenant_id=tenant_id,
    )
    session.add(plugin)
    session.flush()
    return plugin


def _get_or_create_workflow(
    session,
    *,
    name: str,
    description: str,
    plugin_id,
    action: str,
    input_schema: dict[str, Any] | None,
    tenant_id: str,
) -> Workflow:
    workflow = session.query(Workflow).filter(Workflow.name == name).first()
    if workflow:
        if input_schema and not workflow.input_schema:
            workflow.input_schema = input_schema
        return workflow
    workflow = Workflow(
        name=name,
        description=description,
        plugin_id=plugin_id,
        action=action,
        input_schema=input_schema,
        created_by="system",
        tenant_id=tenant_id,
    )
    session.add(workflow)
    return workflow


def seed_data() -> None:
    if os.getenv("DB_SEED", "true").lower() != "true":
        return
    with session_scope() as session:
        try:
            session.query(Plugin).count()
        except (OperationalError, ProgrammingError):
            return
        tenant_id = "default"
        gateway_endpoint = os.getenv("PLUGIN_GATEWAY_URL", "http://plugin-gateway:8002/invoke")
        workflow_invoke_url = os.getenv(
            "WORKFLOW_ADAPTER_URL",
            "http://workflow-adapter:9004/invoke",
        )

        airflow_plugin = _get_or_create_plugin(
            session,
            name="airflow",
            version="v1",
            plugin_type="workflow",
            endpoint=gateway_endpoint,
            actions={"trigger_dag": {"description": "Trigger an Airflow DAG"}},
            allowed_roles={"run": ["operator", "admin"]},
            auth_type="none",
            auth_ref=None,
            auth_config={"invoke_url": workflow_invoke_url},
            tenant_id=tenant_id,
        )

        airflow_workflows = [
            (
                "airflow-daily-health",
                "Trigger daily health DAG",
                "trigger_dag:dummy_daily_health",
                {
                    "type": "object",
                    "required": ["service_name"],
                    "properties": {"service_name": {"type": "string"}},
                },
            ),
            (
                "airflow-cache-refresh",
                "Trigger cache refresh DAG",
                "trigger_dag:dummy_cache_refresh",
                {
                    "type": "object",
                    "required": ["cache_name"],
                    "properties": {"cache_name": {"type": "string"}},
                },
            ),
            (
                "airflow-cost-report",
                "Trigger cost report DAG",
                "trigger_dag:dummy_cost_report",
                {
                    "type": "object",
                    "required": ["billing_period"],
                    "properties": {"billing_period": {"type": "string"}},
                },
            ),
            (
                "airflow-index-rebuild",
                "Trigger index rebuild DAG",
                "trigger_dag:dummy_index_rebuild",
                {
                    "type": "object",
                    "required": ["index_name"],
                    "properties": {"index_name": {"type": "string"}},
                },
            ),
        ]
        for name, description, action, input_schema in airflow_workflows:
            _get_or_create_workflow(
                session,
                name=name,
                description=description,
                plugin_id=airflow_plugin.id,
                action=action,
                input_schema=input_schema,
                tenant_id=tenant_id,
            )

        jenkins_plugin = _get_or_create_plugin(
            session,
            name="jenkins",
            version="v1",
            plugin_type="workflow",
            endpoint=gateway_endpoint,
            actions={"trigger_job": {"description": "Trigger a Jenkins job"}},
            allowed_roles={"run": ["operator", "admin"]},
            auth_type="none",
            auth_ref=None,
            auth_config={"invoke_url": workflow_invoke_url},
            tenant_id=tenant_id,
        )

        jenkins_workflows = [
            (
                "jenkins-dummy-build",
                "Trigger dummy build job",
                "trigger_job:dummy-build",
                {
                    "type": "object",
                    "required": ["branch"],
                    "properties": {"branch": {"type": "string"}},
                },
            ),
            (
                "jenkins-dummy-test",
                "Trigger dummy test job",
                "trigger_job:dummy-test",
                {
                    "type": "object",
                    "required": ["suite"],
                    "properties": {"suite": {"type": "string"}},
                },
            ),
            (
                "jenkins-dummy-deploy",
                "Trigger dummy deploy job",
                "trigger_job:dummy-deploy",
                {
                    "type": "object",
                    "required": ["environment"],
                    "properties": {"environment": {"type": "string"}},
                },
            ),
            (
                "jenkins-dummy-backup",
                "Trigger dummy backup job",
                "trigger_job:dummy-backup",
                {
                    "type": "object",
                    "required": ["backup_bucket"],
                    "properties": {"backup_bucket": {"type": "string"}},
                },
            ),
        ]
        for name, description, action, input_schema in jenkins_workflows:
            _get_or_create_workflow(
                session,
                name=name,
                description=description,
                plugin_id=jenkins_plugin.id,
                action=action,
                input_schema=input_schema,
                tenant_id=tenant_id,
            )

        n8n_plugin = _get_or_create_plugin(
            session,
            name="n8n",
            version="v1",
            plugin_type="workflow",
            endpoint=gateway_endpoint,
            actions={"trigger_workflow": {"description": "Trigger an n8n workflow webhook"}},
            allowed_roles={"run": ["operator", "admin"]},
            auth_type="none",
            auth_ref=None,
            auth_config={"invoke_url": workflow_invoke_url},
            tenant_id=tenant_id,
        )

        n8n_workflows = [
            (
                "n8n-health-check",
                "Trigger n8n health check workflow",
                "trigger_workflow:autonoma-health-check",
                {
                    "type": "object",
                    "required": ["service_name"],
                    "properties": {"service_name": {"type": "string"}},
                },
            ),
            (
                "n8n-cache-refresh",
                "Trigger n8n cache refresh workflow",
                "trigger_workflow:autonoma-cache-refresh",
                {
                    "type": "object",
                    "required": ["cache_name"],
                    "properties": {"cache_name": {"type": "string"}},
                },
            ),
            (
                "n8n-cost-report",
                "Trigger n8n cost report workflow",
                "trigger_workflow:autonoma-cost-report",
                {
                    "type": "object",
                    "required": ["billing_period"],
                    "properties": {"billing_period": {"type": "string"}},
                },
            ),
            (
                "n8n-index-rebuild",
                "Trigger n8n index rebuild workflow",
                "trigger_workflow:autonoma-index-rebuild",
                {
                    "type": "object",
                    "required": ["index_name"],
                    "properties": {"index_name": {"type": "string"}},
                },
            ),
        ]
        for name, description, action, input_schema in n8n_workflows:
            _get_or_create_workflow(
                session,
                name=name,
                description=description,
                plugin_id=n8n_plugin.id,
                action=action,
                input_schema=input_schema,
                tenant_id=tenant_id,
            )

        gitops_plugin = _get_or_create_plugin(
            session,
            name="gitops",
            version="v1",
            plugin_type="workflow",
            endpoint=gateway_endpoint,
            actions={"create_change": {"description": "Create GitOps change request"}},
            allowed_roles={"run": ["operator", "admin"]},
            auth_type="none",
            auth_ref=None,
            auth_config={},
            tenant_id=tenant_id,
        )
        _get_or_create_workflow(
            session,
            name="gitops-change",
            description="Create a GitOps change via plugin gateway",
            plugin_id=gitops_plugin.id,
            action="create_change",
            input_schema=None,
            tenant_id=tenant_id,
        )

        _get_or_create_plugin(
            session,
            name="vault-resolver",
            version="v1",
            plugin_type="secret",
            endpoint=gateway_endpoint,
            actions={"resolve": {"description": "Resolve secrets from Vault"}},
            allowed_roles={"resolve": ["operator", "admin"]},
            auth_type="bearer",
            auth_ref="env:VAULT_TOKEN",
            auth_config={
                "provider": "vault",
                "addr": os.getenv("VAULT_ADDR", "http://vault:8200"),
                "mount": os.getenv("VAULT_KV_MOUNT", "kv"),
            },
            tenant_id=tenant_id,
        )
