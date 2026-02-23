package autonoma.decision

test_default_deny {
    not allow
    deny_reasons["default_deny"]
}

test_policy_allows_auth_me {
    allow with input as {"action": "auth:me"}
}

test_policy_requires_approval_for_prod_run {
    not allow with input as {"action": "workflow:run", "parameters": {"environment": "prod"}}
    deny_reasons["requires_approval"] with input as {"action": "workflow:run", "parameters": {"environment": "prod"}}
    required_approvals == ["human_approval"] with input as {"action": "workflow:run", "parameters": {"environment": "prod"}}
}

test_policy_allows_dev_run {
    allow with input as {"action": "workflow:run", "parameters": {"environment": "dev"}}
    not deny_reasons["default_deny"] with input as {"action": "workflow:run", "parameters": {"environment": "dev"}}
}

test_policy_allows_agent_run {
    allow with input as {"action": "agent:run", "parameters": {"environment": "prod"}}
}

test_policy_allows_plugin_invoke_airflow {
    allow with input as {"action": "plugin:invoke", "resource": {"plugin": "airflow"}}
}

test_policy_allows_plugin_invoke_jenkins {
    allow with input as {"action": "plugin:invoke", "resource": {"plugin": "jenkins"}}
}

test_policy_allows_plugin_invoke_n8n {
    allow with input as {"action": "plugin:invoke", "resource": {"plugin": "n8n"}}
}

test_policy_allows_plugin_invoke_secret {
    allow with input as {"action": "plugin:invoke", "resource": {"plugin": "vault-resolver", "action": "resolve"}}
}

test_policy_denies_unknown_plugin {
    not allow with input as {"action": "plugin:invoke", "resource": {"plugin": "unknown"}}
}
