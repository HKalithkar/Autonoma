---
name: autonoma-architecture-implementer
description: Translate the Autonoma architecture into implementable services, contracts, and milestones; generate OpenAPI, event schemas, and clear module boundaries.
---

# Architecture → Implementable Design (Autonoma)

## Inputs
- Autonoma architecture spec (agents, MCP plugin layer, GitOps, HITL, memory stores, UI/API, observability, governance, agent evals).

## What to produce
1. Service decomposition:
   - UI/API
   - Orchestrator + Event Coordinator + Security Guardian
   - Reasoning/Planning Engine interface
   - MCP Plugin Gateway + Plugin Registry
   - GitOps Engine integration service
   - HITL Approval service
   - Memory stores (vector + time-series + shared state)
   - Observability + audit pipeline
   - Governance (RBAC + policy + audit)
   - Agent evaluation + safety gating

2. Contracts
- OpenAPI endpoints for API layer + internal service calls
- Event bus topics + message schemas (JSON Schema)
- Database schemas (Postgres recommended for transactional metadata)

3. Implementation plan (thin vertical slices)
- Slice A: Auth + RBAC + API scaffolding + minimal UI
- Slice B: Register/trigger workflows via Plugin Gateway + audit
- Slice C: Agents + orchestrations + HITL gate
- Slice D: Observability + eval gating + policy enforcement

## Rules
- Prefer explicit contracts over “implicit” service calls.
- Every cross-service call carries:
  - Correlation ID
  - Actor identity (user or agent service identity)
  - Tenant/workspace ID (even if single-tenant initially)
- Every externally-effecting action is auditable.

## Deliverables
- `docs/system-design.md` (service map + contracts)
- `docs/contracts/openapi.yaml`
- `docs/contracts/events/*.schema.json`
- `docs/milestones.md` with slices and exit criteria
