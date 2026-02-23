# Security Practices

## Principles
- Default deny on every endpoint and action.
- Enforce RBAC + policy checks server-side.
- No secrets in git, logs, traces, or test snapshots.
- All externally-effecting actions are audited.
- Every request carries correlation_id, actor_id, tenant_id.

## Secret Handling
- Use environment variables and `.env` locally.
- Store credentials as references for future vault integration.
- Redact sensitive fields at service boundaries.

## Logging and Auditing
- Use structured logs with explicit allowlists.
- Emit audit events for authz decisions, policy decisions, plugin calls, and approvals.
- Audit events are stored in the API audit table and exposed via `GET /v1/audit` for UI visibility.
- External forwarding is optional via `AUDIT_FORWARD_SYSLOG=true` (syslog) or
  `AUDIT_FORWARD_HTTP_URL` (HTTP endpoint). Set `AUDIT_FORWARD_HTTP_HEADERS`
  to a JSON object for auth headers.

## Service-to-Service
- Require service identity for internal calls.
- Enforce policy checks via the OPA service.

## Authentication
- OIDC is the source of truth for user identity and roles.
- JWT validation checks issuer, audience, expiry, and allowed algorithms.
- Sessions are stored in secure HTTP-only cookies.

## Policy Decisions
- All policy decisions include allow/deny, reasons, and required approvals.
- Policy inputs include correlation_id, actor_id, and tenant_id for traceability.
