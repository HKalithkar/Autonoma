---
name: autonoma-repo-bootstrap
description: Bootstrap a secure, test-first Autonoma monorepo (backend, frontend, infra) with consistent tooling, linting, CI scaffolding, and coding standards.
---

# Autonoma Repo Bootstrap (Security-first + TDD)

## When to use
- Starting a new Autonoma repo or restructuring into a clean monorepo.
- You want predictable, repeatable dev+test loops and baseline security controls from day 0.

## Non-negotiables
- Prefer clarity over cleverness.
- Test-first (TDD) for core logic; every new module ships with unit tests.
- Zero secrets in git; use env vars + local `.env` + secret providers later.
- Explicit interfaces between services (OpenAPI + typed clients).
- All services are container-friendly.

## Target structure
Create or refactor to:

- `apps/api/` (FastAPI or equivalent)
- `apps/web/` (Next.js)
- `apps/agent_runtime/` (LangGraph/LangChain workflows, workers)
- `apps/plugin_gateway/` (MCP gateway service)
- `apps/policy/` (OPA bundle + policy tests)
- `libs/` (shared types, auth helpers, event schemas)
- `infra/` (docker compose, local k8s manifests, helm skeleton if needed)
- `docs/` (architecture notes, ADRs)

## Tasks
1. Initialize toolchain:
   - Python: `uv`, `ruff`, `mypy`, `pytest`, `pytest-cov`
   - Node: `pnpm` (or npm), `eslint`, `prettier`, `vitest`/`jest`
2. Add consistent formatting/linting configs.
3. Add `Makefile` (or `taskfile`) with:
   - `make test`, `make lint`, `make format`, `make dev`, `make up`, `make down`
4. Add baseline CI workflow:
   - Run unit tests + lint for Python/Node
   - Dependency vulnerability scan
5. Add baseline security docs:
   - `docs/SECURITY.md` (threat model outline, secret handling rules)
   - `docs/ADR/` starter template

## Deliverables
- Repo structure created
- CI pipeline runs green on first commit
- `README.md` with dev setup + commands
- All linters configured; tests pass

## Review checklist
- No plaintext credentials committed
- Minimal privileges by default (future RBAC-ready)
- Stable module boundaries (no circular dependencies)
