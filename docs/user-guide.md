# User Guide

This guide describes how to use Autonoma from the web UI.

## Login
1. Open the web UI.
2. Click "Log in with OIDC".
3. Authenticate with Keycloak.

After login, use the left navigation to switch between Home, Chat, Workflows,
Plugins, Events, Audits, Dashboard, Memory, Settings, IAM, and Help.

## Profile
Use the profile button in the top-right header to open your account profile.
It shows the display name, actor ID, tenant, roles, and permissions. The
"Change password" link opens the IAM account console (Keycloak) when configured.
If IAM is configured and you have access, IAM roles are shown alongside session roles.

## Workflows
- Register workflows and trigger runs from the Workflows tab.
- Use the search field to filter workflows.
- Select an environment (`dev`, `stage`, `prod`), provide JSON parameters, and
  click "Run".
- A run ID and job ID are created and visible in the runs panel.

## Agents
- The Agents tab shows status, run history, and LLM configuration.
- Use "Create agent run" to plan or execute tasks with the orchestrator.

## Approvals (Home)
- If a policy requires approval, a run will be marked as `pending_approval`.
- Approvers can approve/deny from the Home tab.
- Approved runs continue execution; denied runs stop.

## Events
- The Events tab shows alerts and agent response trails.
- The feed updates in real time; use the pause/resume toggle to control live updates.
- Chat-triggered actions are surfaced here with action trails so you can follow
  workflow runs, plugin invocations, and approvals outside of the chat view.

## Audit trail
- The Audits tab shows policy decisions, authz checks, plugin invocations, and
  LLM calls (redacted).
- Use filters to narrow by actor, event type, or time window; filters are case-insensitive
  and match partial values.

## Chat assistant
- The Chat tab lets you ask for workflows, approvals, and audit events.
- The assistant can:
  - list workflows and plugins
  - create workflow runs
  - fetch approval details
  - check audit events
- Chat history is stored per user.
- Each chat request produces an event trail (without prompt content) visible in
  the Events tab for operational follow-up.

### Triggering workflows from chat
Use an explicit run intent and include required params:

Example:
```
run workflow jenkins-dummy-build with branch: dev
```

You can also pass JSON params:
```
run workflow jenkins-dummy-build with {"branch": "dev"}
```

If required fields are missing, the assistant will reply with the required
fields and an example command to retry.

## Memory search
- The Memory tab searches long-term memory documents.
- Use keyword queries to retrieve summaries and references.

## MCP plugins
- MCP servers can be registered as plugins (`plugin_type=mcp`) and invoked via workflows
  using `tools/list` or `tools/call`. See `docs/workflows.md` for examples.

## Admin: LLM configuration
Admins can update agent LLM config:
- API URL and model per agent type.
- `api_key_ref` must be `env:VAR` or `secretkeyref:plugin:<name>:<path>`.

## Troubleshooting
- If login fails, verify Keycloak is reachable.
- If a run is blocked, check approvals or policy decisions in the audit panel.
