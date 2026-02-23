# Auth & RBAC (Slice 1)

## Overview
Autonoma uses OIDC for user authentication and RBAC for authorization. The API validates
JWTs on every protected endpoint and maps roles to permissions. Default deny applies
to all actions unless explicitly allowed.

## Roles
- `viewer`: basic read access
- `operator`: workflow read/run
- `approver`: approval actions
- `admin`: full access
- `security_admin`: policy/audit-focused access

## Permissions
Permissions are scoped as `domain:action` with optional wildcards:
- `auth:me`
- `workflow:read`, `workflow:run`
- `approval:read`, `approval:write`
- `audit:read`, `audit:write`
- `plugin:*`
- `rbac:*`
- `audit:*`
- `agent:run`
- `agent:config:read`, `agent:config:write`
- `iam:read`, `iam:write`

## Local OIDC (Keycloak)
The docker-compose environment includes a Keycloak container for local OIDC.
Defaults are defined in `.env.example` and can be overridden in `.env`.
The dev realm disables TLS enforcement (`sslRequired: none`) to avoid the
"HTTPS required" error during local HTTP login flows.
This is enforced by a one-shot `keycloak-init` service that runs after Keycloak
is healthy and updates the realm settings via `kcadm`.

## Production HTTPS
For production, enforce HTTPS at the IdP and edge:
- Set `sslRequired=external` (or `all`) for the realm.
- Terminate TLS at the gateway/load balancer and forward `X-Forwarded-*` headers.
- Configure Keycloak with a fixed external hostname and HTTPS URLs.

Example (env vars):
```
KC_HTTP_ENABLED=false
KC_HOSTNAME=auth.example.com
KC_HOSTNAME_ADMIN=auth.example.com
KC_HOSTNAME_STRICT=true
KC_HOSTNAME_STRICT_HTTPS=true
KC_PROXY_HEADERS=xforwarded
```

### Demo user
- Username: `demo_admin`
- Password: `demo_admin_pass`
- Realm: `autonoma`

### Approver demo user
- Username: `demo_approver`
- Password: `demo_approver_pass`
- Realm: `autonoma`

## Environment variables
API expects the following:
- `OIDC_ISSUER`
- `OIDC_AUTH_URL`
- `OIDC_AUTH_URL_DOCKER` (optional; used when the request host is `web` inside docker-compose)
- `OIDC_TOKEN_URL`
- `OIDC_JWKS_URL`
- `OIDC_CLIENT_ID`
- `OIDC_CLIENT_SECRET` (optional)
- `OIDC_REDIRECT_URI`
- `UI_BASE_URL` (optional; UI base to redirect to after login)
- `OIDC_AUDIENCE`
- `OIDC_SCOPES`
- `OIDC_ALLOWED_ALGS`
- `AUTH_COOKIE_SECURE`
- `IAM_PROVIDER` (e.g. `keycloak`)
- `IAM_ADMIN_URL`
- `IAM_TOKEN_URL`
- `IAM_CLIENT_ID`
- `IAM_CLIENT_SECRET`
- `IAM_REALM`

## Auth flow
1) UI redirects to `/v1/auth/login` on the API.
2) API redirects to the IdP (Keycloak).
3) IdP redirects back to `/v1/auth/callback`.
4) API exchanges the code, sets `autonoma_access_token` cookie, and redirects to UI.

## Frontend routing
The Vite dev server proxies `/v0`, `/docs`, and `/openapi.json` to the API container.
If you need a hardcoded API URL, set `VITE_API_URL` in `.env`.

## E2E login test
Run `make e2e` after `make up` to verify the login link redirects to Keycloak.

## Audit
Every allow/deny decision is logged with `correlation_id`, `actor_id`, and `tenant_id`.
