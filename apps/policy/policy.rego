package autonoma.decision

# Default deny. Specific allow rules will be added in later slices.
default allow = false

default required_approvals = []

allow {
    input.action == "auth:me"
}

allow {
    input.action == "policy:check"
}

allow {
    input.action == "workflow:run"
    input.parameters.environment != "prod"
}

allow {
    input.action == "agent:run"
}

allow {
    input.action == "plugin:invoke"
    input.resource.plugin == "airflow"
}

allow {
    input.action == "plugin:invoke"
    input.resource.plugin == "gitops"
}

allow {
    input.action == "plugin:invoke"
    input.resource.plugin == "jenkins"
}

allow {
    input.action == "plugin:invoke"
    input.resource.plugin == "n8n"
}

allow {
    input.action == "plugin:invoke"
    input.resource.action == "resolve"
}

deny_reasons["default_deny"] {
    not allow
}

deny_reasons["requires_approval"] {
    input.action == "workflow:run"
    input.parameters.environment == "prod"
}

required_approvals := ["human_approval"] {
    input.action == "workflow:run"
    input.parameters.environment == "prod"
}

decision := {
    "allow": allow,
    "deny_reasons": deny_reasons,
    "required_approvals": required_approvals,
}
