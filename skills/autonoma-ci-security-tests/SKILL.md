---
name: autonoma-ci-security-tests
description: Add enterprise-grade CI: unit/integration tests, SAST, dependency scanning, container scanning, policy tests, and security regression tests.
---

# CI + Security Testing

## Pipeline stages
1. Lint/format (Python + Node)
2. Unit tests with coverage thresholds
3. Integration tests (docker compose test profile)
4. Policy tests (`opa test`)
5. Security:
   - dependency vuln scan (pip/npm)
   - SAST (bandit/semgrep)
   - container image scan
6. Minimal release artifact build

## Required tests
- Auth/RBAC negative tests
- Policy deny tests
- Plugin gateway schema validation tests
- Agent safety regression tests (prompt injection attempts)

## Deliverables
- CI config files
- `SECURITY_TESTS.md` describing what is covered and how to run locally
