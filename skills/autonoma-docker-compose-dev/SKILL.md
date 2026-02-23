---
name: autonoma-docker-compose-dev
description: Create a full local dev environment with docker-compose: API, web, agents, plugin gateway, policy, postgres, redis, and observability stack.
---

# Local Dev with Docker Compose

## Services (minimum)
- api
- web
- agent-runtime
- plugin-gateway
- policy (OPA)
- postgres
- redis
- otel-collector (+ optional grafana/prometheus)

## Requirements
- One-command startup: `docker compose up`
- Healthchecks for all containers
- Seed data: demo users/roles + demo workflows/plugins
- Local TLS optional; at least support it via config

## Deliverables
- `infra/docker-compose.yml`
- `.env.example`
- `make up/down/dev`
- Smoke tests that verify:
  - login works
  - workflow can be registered
  - workflow trigger returns job id
  - audit row written
