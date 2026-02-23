---
name: autonoma-db-schema
description: Design and implement Autonoma transactional DB schemas + migrations for workflows, plugins, runs, approvals, audit, identities, and evaluation scores.
---

# Autonoma Database Schema (Transactional)

## Recommended DB
- Postgres for transactional metadata.
- Keep vector/time-series in dedicated stores; DB holds references.

## Core entities (must-have)
- Tenancy/workspace (even if single-tenant at MVP)
- Users, roles, permissions
- Agents (service identities), agent roles, agent keys
- Workflow definitions (registered pre-existing workflows)
- Workflow runs (job IDs, status, timestamps, outputs)
- Plugin registry (capabilities, versions, auth refs)
- Plugin invocations (request/response metadata, redaction)
- Approvals (HITL gates, approver, decision, rationale)
- Policies (OPA bundle versions, decisions, traces)
- Audit log (append-only events, signatures optional)
- Agent evaluation scores (per action/run)

## Requirements
- Use migrations (Alembic / Prisma / Flyway).
- Add indexes for:
  - `workflow_runs(status, created_at)`
  - `audit_log(correlation_id, created_at)`
  - `plugin_invocations(plugin_id, created_at)`
- Design for immutability where needed:
  - Audit log uses append-only semantics.
- Redact sensitive fields at persistence boundary.

## Deliverables
- Schema + migrations
- ORM models + repository layer
- Unit tests for migrations and core queries
- Seed data for dev (roles + demo workflows)

## Review checklist
- No secrets stored in plaintext
- Tenant/workspace ID on every row (or future-proofed)
- Clear retention strategy for audit + invocations
