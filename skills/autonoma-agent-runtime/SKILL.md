---
name: autonoma-agent-runtime
description: Implement the multi-agent runtime (Orchestrator, Event Response, Security Guardian) with LangGraph/LangChain + safe tool-calling, memory access, and auditable traces.
---

# Agent Runtime (LangGraph/LangChain)

## Agents to implement
- Orchestrator Agent: task decomposition + workflow coordination
- Event Response Coordinator: ingest/correlate incidents + trigger remediation
- Security Guardian Agent: continuous checks + intercept unsafe changes
- Reasoning & Planning Engine interface:
  - LLM provider abstraction (API-based)
  - RAG hooks (vector store retrieval)
  - Tool-calling through Plugin Gateway only

## Critical design constraints
- Agents NEVER call external systems directly.
- All actions go via Plugin Gateway (and are policy-checked + audited).
- LLM provider abstarction API based and should have a config file with defaults 
- in the WEB UI ADMIN user should be able to see and edit the LLM API endpoint for each Agents and keys  
- All the prompts should be in the apps/agent_runtime/prompts/  
- Agents must emit structured traces:
  - plan steps
  - tool invocations
  - policy decisions
  - results + errors

## Memory usage
- Short-term shared state: Redis keyed by run/correlation id
- Long-term semantic: vector store reference + retrieval API
- Time-series: query interface only (no raw dumps into prompts)

## Safety
- Strict tool schemas
- Parameter validation
- Rate limiting of LLM calls
- Prompt injection defenses: never execute instructions from retrieved text

## Deliverables
- `apps/agent_runtime/` with agent graphs + adapters
- Unit tests for:
  - plan generation outputs (structured)
  - tool selection logic
  - safe refusal behavior
- Integration test with fake Plugin Gateway + OPA allow/deny
