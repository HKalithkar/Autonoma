---
name: autonoma-auth-oidc-rbac
description: Implement OAuth2/OIDC auth + RBAC enforcement end-to-end across UI/API and service-to-service agent identities with least privilege.
---

# Auth (OIDC) + RBAC + Service Identities

## Goals
- Human auth: OIDC with roles/groups.
- API auth: JWT validation, scopes, audience, expiry.
- Agent-to-agent security: mTLS + workload identity + short-lived tokens.

## Must implement
1. OIDC login flow (web) + token storage (secure cookies).
2. API middleware:
   - Validate JWT
   - Extract user claims → roles → permissions
   - Enforce RBAC on every endpoint
3. Service identities for internal agents/services:
   - Each service gets its own identity and role.
   - Requests between services include:
     - service identity token (and mTLS)
4. Authorization model
- Roles: `viewer`, `operator`, `approver`, `admin`, `security_admin`
- Permissions: granular actions (register workflow, trigger run, approve, manage plugins, view audit)

## Security rules
- Default deny.
- No “admin” shortcuts in prod paths.
- Audit every auth failure + authorization deny (with correlation id).

## Deliverables
- Auth server config (dev realm export if using Keycloak)
- API auth middleware + RBAC library
- Frontend auth integration + protected routes
- Tests:
  - JWT validation tests
  - RBAC matrix tests
  - Negative tests (deny-by-default)

## Review checklist
- Least privilege per agent/service
- Token rotation/expiry handled
- No sensitive claims logged
