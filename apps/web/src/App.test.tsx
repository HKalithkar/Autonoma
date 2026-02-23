import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

type MockResponse = {
  ok: boolean;
  json: () => Promise<unknown>;
};

const mockFetch = (response: MockResponse) => {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
};

const mockFetchSequence = (responses: MockResponse[]) => {
  const fetchMock = vi.fn();
  responses.forEach((response) => fetchMock.mockResolvedValueOnce(response));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("App auth flow", () => {
  it("renders OIDC login link when unauthenticated", async () => {
    vi.stubEnv("VITE_API_URL", "");
    mockFetch({ ok: false, json: async () => ({}) });

    render(<App />);

    const link = await screen.findByRole("link", { name: /log in with oidc/i });
    expect(link).toHaveAttribute("href", "/v1/auth/login");
  });

  it("renders authenticated state and logout action", async () => {
    vi.stubEnv("VITE_API_URL", "http://localhost:8000");
    const fetchMock = vi.fn(async (input: RequestInfo) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.endsWith("/v1/auth/me")) {
        return {
          ok: true,
          json: async () => ({
            actor_id: "user-1",
            tenant_id: "default",
            roles: ["admin"],
            permissions: ["auth:me"]
          })
        };
      }
      if (url.includes("/v1/audit")) {
        return {
          ok: true,
          json: async () => [
            {
              id: "audit-1",
              event_type: "workflow.register",
              outcome: "allow",
              source: "api",
              actor_id: "user-1",
              created_at: "2026-01-01T00:00:00Z",
              details: { description: "Workflow registered (workflow-1)" }
            }
          ]
        };
      }
      return { ok: true, json: async () => [] };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    const nameNodes = await screen.findAllByText("user-1");
    expect(nameNodes.length).toBeGreaterThan(0);
    const logoutButton = screen.getByRole("button", { name: /log out/i });
    const form = logoutButton.closest("form");

    await waitFor(() => {
      expect(form).not.toBeNull();
      expect(form).toHaveAttribute("action", "http://localhost:8000/v1/auth/logout");
    });
  });

  it("refreshes session on 401 and renders authenticated state", async () => {
    vi.stubEnv("VITE_API_URL", "http://localhost:8000");
    const fetchMock = vi.fn(async (input: RequestInfo) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.endsWith("/v1/auth/me")) {
        const attempt = fetchMock.mock.calls.filter(
          ([callUrl]) => (typeof callUrl === "string" ? callUrl : callUrl.url).endsWith("/v1/auth/me")
        ).length;
        if (attempt === 1) {
          return { ok: false, status: 401, json: async () => ({}) };
        }
        return {
          ok: true,
          status: 200,
          json: async () => ({
            actor_id: "user-1",
            tenant_id: "default",
            roles: ["admin"],
            permissions: ["auth:me"]
          })
        };
      }
      if (url.endsWith("/v1/auth/refresh")) {
        return { ok: true, status: 204, json: async () => ({}) };
      }
      return { ok: true, status: 200, json: async () => [] };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    const nameNodes = await screen.findAllByText("user-1");
    expect(nameNodes.length).toBeGreaterThan(0);
  });

  it("renders approvals inbox when approvals are returned", async () => {
    vi.stubEnv("VITE_API_URL", "http://localhost:8000");
    const fetchMock = vi.fn(async (input: RequestInfo) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.endsWith("/v1/auth/me")) {
        return {
          ok: true,
          json: async () => ({
            actor_id: "user-1",
            tenant_id: "default",
            roles: ["approver"],
            permissions: ["approval:read", "audit:read"]
          })
        };
      }
      if (url.endsWith("/v1/approvals")) {
        return {
          ok: true,
          json: async () => [
            {
              id: "approval-1",
              workflow_id: "workflow-1",
              workflow_run_id: "run-1",
              target_type: "workflow",
              target_name: "Daily Health",
              requested_by: "operator-1",
              required_role: "approver",
              risk_level: "high",
              status: "pending",
              created_at: "2026-01-01T00:00:00Z"
            }
          ]
        };
      }
      if (url.includes("/v1/audit")) {
        return {
          ok: true,
          json: async () => [
            {
              id: "audit-1",
              event_type: "approval.requested",
              outcome: "allow",
              source: "api",
              actor_id: "user-1",
              created_at: "2026-01-01T00:00:00Z",
              details: { description: "Approval requested for workflow" }
            }
          ]
        };
      }
      return { ok: true, json: async () => [] };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await screen.findByText("Approvals");
    await screen.findByText("Daily Health");
    expect(screen.getByRole("button", { name: /approve/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /audits/i }));
    await screen.findByRole("button", { name: /apply filters/i });
    expect(screen.getByRole("button", { name: /reset filters/i })).toBeInTheDocument();
  });

  it("submits an agent run from the UI", async () => {
    vi.stubEnv("VITE_API_URL", "http://localhost:8000");
    const fetchMock = mockFetchSequence([
      {
        ok: true,
        json: async () => ({
          actor_id: "user-1",
          tenant_id: "default",
          roles: ["operator"],
          permissions: ["agent:run"]
        })
      },
      { ok: true, json: async () => [] },
      { ok: true, json: async () => [] },
      { ok: true, json: async () => [] },
      { ok: true, json: async () => [] },
      { ok: true, json: async () => [] },
      { ok: true, json: async () => [] },
      { ok: true, json: async () => [] },
      { ok: true, json: async () => [] },
      { ok: true, json: async () => [] },
      {
        ok: true,
        json: async () => ({ run_id: "run-123", status: "planned" })
      },
      {
        ok: true,
        json: async () => [
          {
            id: "run-123",
            goal: "Refresh cache",
            environment: "dev",
            status: "planned",
            requested_by: "user-1",
            created_at: "2026-01-01T00:00:00Z"
          }
        ]
      }
    ]);

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: /agents/i }));
    const goalInput = await screen.findByPlaceholderText(/goal/i);
    fireEvent.change(goalInput, { target: { value: "Refresh cache" } });
    fireEvent.click(screen.getByRole("button", { name: /create agent run/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/v1/agent/runs", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          goal: "Refresh cache",
          environment: "dev",
          tools: ["plugin_gateway.invoke"],
          documents: []
        })
      });
    });
  });

  it("shows a workflow submission modal with run details", async () => {
    vi.stubEnv("VITE_API_URL", "http://localhost:8000");
    const fetchMock = vi.fn(async (input: RequestInfo) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.endsWith("/v1/auth/me")) {
        return {
          ok: true,
          json: async () => ({
            actor_id: "user-1",
            tenant_id: "default",
            roles: ["operator"],
            permissions: ["workflow:read", "agent:run"]
          })
        };
      }
      if (url.endsWith("/v1/plugins")) {
        return { ok: true, json: async () => [] };
      }
      if (url.endsWith("/v1/workflows")) {
        return {
          ok: true,
          json: async () => [
            {
              id: "workflow-1",
              name: "Daily Health",
              description: "Daily check",
              plugin_id: "plugin-1",
              action: "run",
              input_schema: null
            }
          ]
        };
      }
      if (url.endsWith("/v1/approvals")) {
        return { ok: true, json: async () => [] };
      }
      if (url.includes("/v1/runs")) {
        return {
          ok: true,
          json: async () => [
            {
              id: "run-42",
              workflow_id: "workflow-1",
              workflow_name: "Daily Health",
              status: "succeeded",
              job_id: "job-9",
              environment: "dev",
              created_at: "2026-01-01T00:00:00Z",
              approval_id: null,
              approval_status: null
            }
          ]
        };
      }
      if (url.endsWith("/v1/agent/configs")) {
        return { ok: true, json: async () => [] };
      }
      if (url.endsWith("/v1/agent/runs")) {
        return { ok: true, json: async () => [] };
      }
      if (url.endsWith("/v1/events")) {
        return { ok: true, json: async () => [] };
      }
      if (url.endsWith("/v1/chat/sessions")) {
        return { ok: true, json: async () => [] };
      }
      if (url.includes("/v1/audit")) {
        return { ok: true, json: async () => [] };
      }
      if (url.endsWith("/v1/workflows/workflow-1/runs")) {
        return {
          ok: true,
          json: async () => ({
            run_id: "run-42",
            status: "submitted",
            job_id: "job-9"
          })
        };
      }
      return { ok: true, json: async () => [] };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: /workflows/i }));
    const workflowLabels = await screen.findAllByText(/daily health/i);
    expect(workflowLabels.length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    const dialog = await screen.findByRole("dialog", { name: /workflow submission status/i });
    await within(dialog).findByText(/workflow (submitted|completed)/i);
    await within(dialog).findByText("run-42");
    await within(dialog).findByText("job-9");
    await within(dialog).findByText("succeeded");
  });

  it("renders v1 runtime timeline cards in run details modal", async () => {
    vi.stubEnv("VITE_API_URL", "http://localhost:8000");
    const fetchMock = vi.fn(async (input: RequestInfo) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.endsWith("/v1/auth/me")) {
        return {
          ok: true,
          json: async () => ({
            actor_id: "user-1",
            tenant_id: "default",
            roles: ["operator"],
            permissions: ["workflow:read", "approval:write"]
          })
        };
      }
      if (url.endsWith("/v1/plugins")) return { ok: true, json: async () => [] };
      if (url.endsWith("/v1/workflows")) return { ok: true, json: async () => [] };
      if (url.endsWith("/v1/approvals")) return { ok: true, json: async () => [] };
      if (url.endsWith("/v1/runs")) {
        return {
          ok: true,
          json: async () => [
            {
              id: "run-1",
              workflow_id: "wf-1",
              workflow_name: "Daily Health",
              status: "running",
              environment: "dev",
              created_at: "2026-01-01T00:00:00Z",
              params: { region: "us-east-1" }
            }
          ]
        };
      }
      if (url.endsWith("/v1/agent/configs")) return { ok: true, json: async () => [] };
      if (url.endsWith("/v1/agent/runs")) return { ok: true, json: async () => [] };
      if (url.endsWith("/v1/events")) return { ok: true, json: async () => [] };
      if (url.endsWith("/v1/chat/sessions")) return { ok: true, json: async () => [] };
      if (url.includes("/v1/audit")) return { ok: true, json: async () => [] };
      if (url.includes("/v1/runs/run-1/timeline")) {
        return {
          ok: true,
          json: async () => ({
            run_id: "run-1",
            events: [
              {
                event_id: "evt-1",
                event_type: "policy.decision.recorded",
                schema_version: "v1",
                run_id: "run-1",
                step_id: "step-1",
                timestamp: "2026-02-01T12:00:00Z",
                correlation_id: "corr-1",
                actor_id: "operator-1",
                tenant_id: "default",
                agent_id: "security_guardian_worker",
                payload: { outcome: "allow" },
                visibility_level: "tenant",
                redaction: "none"
              }
            ],
            next_event_id: "evt-1"
          })
        };
      }
      return { ok: true, json: async () => [] };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: /workflows/i }));
    fireEvent.click(await screen.findByLabelText("View details for Daily Health"));

    await screen.findByText("Runtime timeline");
    await screen.findByText("policy.decision.recorded");
    await screen.findByText("Policy decision: allow");
  });

  it("shows full runtime events from agent history run details", async () => {
    vi.stubEnv("VITE_API_URL", "http://localhost:8000");
    const fetchMock = vi.fn(async (input: RequestInfo) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.endsWith("/v1/auth/me")) {
        return {
          ok: true,
          json: async () => ({
            actor_id: "user-1",
            tenant_id: "default",
            roles: ["operator"],
            permissions: ["agent:run"]
          })
        };
      }
      if (url.endsWith("/v1/plugins")) return { ok: true, json: async () => [] };
      if (url.endsWith("/v1/workflows")) return { ok: true, json: async () => [] };
      if (url.endsWith("/v1/approvals")) return { ok: true, json: async () => [] };
      if (url.endsWith("/v1/runs")) return { ok: true, json: async () => [] };
      if (url.endsWith("/v1/agent/configs")) return { ok: true, json: async () => [] };
      if (url.endsWith("/v1/agent/runs")) {
        return {
          ok: true,
          json: async () => [
            {
              id: "agent-run-1",
              goal: "Refresh cache safely",
              environment: "dev",
              status: "running",
              requested_by: "user-1",
              created_at: "2026-01-01T00:00:00Z",
              runtime: {
                run_id: "agent-run-1",
                status: "running",
                last_event_type: "policy.decision.recorded",
                updated_at: "2026-01-01T00:01:00Z"
              }
            }
          ]
        };
      }
      if (url.endsWith("/v1/events")) return { ok: true, json: async () => [] };
      if (url.endsWith("/v1/chat/sessions")) return { ok: true, json: async () => [] };
      if (url.includes("/v1/audit")) return { ok: true, json: async () => [] };
      if (url.includes("/v1/runs/agent-run-1/timeline")) {
        return {
          ok: true,
          json: async () => ({
            run_id: "agent-run-1",
            events: [
              {
                event_id: "evt-agent-1",
                event_type: "policy.decision.recorded",
                schema_version: "v1",
                run_id: "agent-run-1",
                step_id: "step-1",
                timestamp: "2026-02-01T12:00:00Z",
                correlation_id: "corr-1",
                actor_id: "operator-1",
                tenant_id: "default",
                agent_id: "security_guardian_worker",
                payload: { outcome: "allow" },
                visibility_level: "tenant",
                redaction: "none"
              }
            ],
            next_event_id: "evt-agent-1"
          })
        };
      }
      return { ok: true, json: async () => [] };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: /agents/i }));
    fireEvent.click(await screen.findByLabelText(/view details for agent run refresh cache safely/i));

    await screen.findByRole("dialog", { name: /agent run details/i });
    await screen.findByText("Runtime timeline");
    await screen.findByText("policy.decision.recorded");
    await screen.findByText("Policy decision: allow");
  });

  it("submits a memory search request", async () => {
    vi.stubEnv("VITE_API_URL", "http://localhost:8000");
    const fetchMock = mockFetchSequence([
      {
        ok: true,
        json: async () => ({
          actor_id: "user-1",
          tenant_id: "default",
          roles: ["operator"],
          permissions: ["memory:read"]
        })
      },
      { ok: true, json: async () => [] },
      { ok: true, json: async () => [] },
      { ok: true, json: async () => [] },
      { ok: true, json: async () => [] },
      { ok: true, json: async () => [] },
      { ok: true, json: async () => [] },
      { ok: true, json: async () => [] },
      { ok: true, json: async () => [] },
      { ok: true, json: async () => [] },
      {
        ok: true,
        json: async () => ({
          results: [
            {
              id: "mem-1",
              score: 0.1,
              text: "plan: refresh caches",
              metadata: { type: "plan", source: "agent-runtime" }
            }
          ]
        })
      }
    ]);

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: /memory/i }));
    const input = await screen.findByPlaceholderText(/search query/i);
    fireEvent.change(input, { target: { value: "refresh cache" } });
    fireEvent.click(screen.getByRole("button", { name: /search memory/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/v1/memory/search", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: "refresh cache",
          top_k: 5,
          filters: {}
        })
      });
    });
  });

  it("renders chat tool results in the conversation", async () => {
    vi.stubEnv("VITE_API_URL", "http://localhost:8000");
    const fetchMock = vi.fn(async (input: RequestInfo) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.endsWith("/v1/auth/me")) {
        return {
          ok: true,
          json: async () => ({
            actor_id: "user-1",
            tenant_id: "default",
            roles: ["operator"],
            permissions: ["chat:run"]
          })
        };
      }
      if (url.endsWith("/v1/chat/sessions")) {
        return {
          ok: true,
          json: async () => [
            { id: "session-1", title: "Ops chat", updated_at: "2026-01-01T00:00:00Z" }
          ]
        };
      }
      if (url.endsWith("/v1/chat/sessions/session-1/messages")) {
        return {
          ok: true,
          json: async () => [
            {
              id: "msg-1",
              role: "assistant",
              content: "Here are the plugins.",
              tool_results: {
                items: [
                  {
                    action: "plugin.list",
                    status: "ok",
                    result: [{ id: "plugin-1", name: "airflow" }]
                  }
                ]
              },
              created_at: "2026-01-01T00:00:00Z"
            }
          ]
        };
      }
      if (url.includes("/v1/audit")) {
        return { ok: true, json: async () => [] };
      }
      return { ok: true, json: async () => [] };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Chat" }));
    await screen.findByText("Ops chat");
    fireEvent.click(screen.getByRole("button", { name: "Ops chat" }));
    await screen.findByText("Plugins: airflow");
  });

  it("renders approval detail in chat responses", async () => {
    vi.stubEnv("VITE_API_URL", "http://localhost:8000");
    const fetchMock = vi.fn(async (input: RequestInfo) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.endsWith("/v1/auth/me")) {
        return {
          ok: true,
          json: async () => ({
            actor_id: "user-1",
            tenant_id: "default",
            roles: ["approver"],
            permissions: ["chat:run"]
          })
        };
      }
      if (url.endsWith("/v1/chat/sessions")) {
        return {
          ok: true,
          json: async () => [
            { id: "session-1", title: "Approvals", updated_at: "2026-01-01T00:00:00Z" }
          ]
        };
      }
      if (url.endsWith("/v1/chat/sessions/session-1/messages")) {
        return {
          ok: true,
          json: async () => [
            {
              id: "msg-1",
              role: "assistant",
              content: "Approval detail.",
              tool_results: {
                items: [
                  {
                    action: "approval.get",
                    status: "ok",
                    result: {
                      id: "approval-1",
                      workflow_name: "daily-health",
                      environment: "prod",
                      status: "pending",
                      run_status: "submitted",
                      requested_by: "operator-1",
                      risk_level: "high"
                    }
                  }
                ]
              },
              created_at: "2026-01-01T00:00:00Z"
            }
          ]
        };
      }
      if (url.includes("/v1/audit")) {
        return { ok: true, json: async () => [] };
      }
      return { ok: true, json: async () => [] };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Chat" }));
    await screen.findByText("Approvals");
    fireEvent.click(screen.getByRole("button", { name: "Approvals" }));
    await screen.findByText(/workflow daily-health/i);
    await screen.findByText(/env prod/i);
  });

  it("renders run detail in chat responses", async () => {
    vi.stubEnv("VITE_API_URL", "http://localhost:8000");
    const fetchMock = vi.fn(async (input: RequestInfo) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.endsWith("/v1/auth/me")) {
        return {
          ok: true,
          json: async () => ({
            actor_id: "user-1",
            tenant_id: "default",
            roles: ["operator"],
            permissions: ["chat:run"]
          })
        };
      }
      if (url.endsWith("/v1/chat/sessions")) {
        return {
          ok: true,
          json: async () => [
            { id: "session-1", title: "Runs", updated_at: "2026-01-01T00:00:00Z" }
          ]
        };
      }
      if (url.endsWith("/v1/chat/sessions/session-1/messages")) {
        return {
          ok: true,
          json: async () => [
            {
              id: "msg-1",
              role: "assistant",
              content: "Run detail.",
              tool_results: {
                items: [
                  {
                    action: "run.get",
                    status: "ok",
                    result: {
                      id: "run-1",
                      workflow_name: "daily-health",
                      environment: "dev",
                      status: "submitted",
                      job_id: "job-123",
                      approval_status: "pending",
                      requested_by: "operator-1",
                      param_keys: ["dag_id"]
                    }
                  }
                ]
              },
              created_at: "2026-01-01T00:00:00Z"
            }
          ]
        };
      }
      if (url.includes("/v1/audit")) {
        return { ok: true, json: async () => [] };
      }
      return { ok: true, json: async () => [] };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Chat" }));
    await screen.findByText("Runs");
    fireEvent.click(screen.getByRole("button", { name: "Runs" }));
    await screen.findByText(/workflow daily-health/i);
    await screen.findByText(/env dev/i);
    await screen.findByText(/Params: dag_id/i);
  });

  it("shows session activity filtered by chat session and correlation id", async () => {
    vi.stubEnv("VITE_API_URL", "http://localhost:8000");
    const fetchMock = vi.fn(async (input: RequestInfo) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.endsWith("/v1/auth/me")) {
        return {
          ok: true,
          json: async () => ({
            actor_id: "user-1",
            tenant_id: "default",
            roles: ["operator"],
            permissions: ["chat:run", "audit:read"]
          })
        };
      }
      if (url.endsWith("/v1/chat/sessions")) {
        return {
          ok: true,
          json: async () => [
            { id: "session-1", title: "Ops chat", updated_at: "2026-01-01T00:00:00Z" }
          ]
        };
      }
      if (url.endsWith("/v1/chat/sessions/session-1/messages")) {
        return {
          ok: true,
          json: async () => [
            {
              id: "msg-1",
              role: "assistant",
              content: "Run accepted.",
              tool_results: { items: [] },
              created_at: "2026-01-01T00:00:00Z"
            }
          ]
        };
      }
      if (url.endsWith("/v1/events")) {
        return {
          ok: true,
          json: async () => [
            {
              id: "evt-chat-1",
              event_type: "chat.run",
              severity: "info",
              summary: "Chat request processed.",
              source: "chat",
              details: { actor_id: "user-1", session_id: "session-1" },
              environment: "dev",
              status: "running",
              correlation_id: "corr-1",
              received_at: "2026-01-01T00:00:00Z"
            },
            {
              id: "evt-run-1",
              event_type: "run.started",
              severity: "info",
              summary: "Workflow run started.",
              source: "runtime-orchestrator",
              details: { actor_id: "service:runtime" },
              environment: "dev",
              status: "running",
              correlation_id: "corr-1",
              received_at: "2026-01-01T00:01:00Z"
            },
            {
              id: "evt-other-1",
              event_type: "chat.run",
              severity: "info",
              summary: "Other session.",
              source: "chat",
              details: { actor_id: "user-1", session_id: "session-other" },
              environment: "dev",
              status: "running",
              correlation_id: "corr-2",
              received_at: "2026-01-01T00:02:00Z"
            }
          ]
        };
      }
      if (url.includes("/v1/audit")) {
        return { ok: true, json: async () => [] };
      }
      return { ok: true, json: async () => [] };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Chat" }));
    await screen.findByText("Session Activity");
    fireEvent.click(screen.getByRole("button", { name: "Ops chat" }));

    await screen.findByText("Chat request processed.");
    await screen.findByText("Workflow run started.");
    expect(screen.queryByText("Other session.")).not.toBeInTheDocument();
  });
});
