# Security Tests

## Local (manual)
- `make policy-test`
- `make lint`
- `make test`
- `make e2e`

## CI (planned)
- SAST: bandit/semgrep
- Dependency scan: pip-audit, npm audit
- Container scan: trivy (planned)

## Python dependency scan notes
`CVE-2024-23342` (ecdsa) has no upstream fixed release available as of now.
CI temporarily ignores this CVE; remove the ignore once a patched ecdsa version ships.
