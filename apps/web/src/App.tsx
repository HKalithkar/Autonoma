import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { APP_NAME, APP_TAGLINE } from "./appInfo";
import "./styles.css";

type AuthState = {
  actor_id: string;
  username?: string | null;
  tenant_id: string;
  roles: string[];
  permissions: string[];
};

type Plugin = {
  id: string;
  name: string;
  version: string;
  plugin_type?: string;
  endpoint: string;
  actions: Record<string, unknown>;
  allowed_roles?: Record<string, unknown>;
  auth_type?: string;
  auth_ref?: string | null;
  auth_config?: Record<string, unknown>;
};

type Workflow = {
  id: string;
  name: string;
  description?: string | null;
  plugin_id: string;
  action: string;
  input_schema?: WorkflowInputSchema | null;
};

type WorkflowInputSchema = {
  type?: string;
  required?: string[];
  properties?: Record<string, { type?: string }>;
};

type WorkflowRunNotice = {
  outcome: "submitted" | "pending" | "failed";
  workflowName: string;
  environment: string;
  runId?: string;
  jobId?: string;
  approvalId?: string;
  approvalStatus?: string | null;
  status?: string;
  paramKeys: string[];
  error?: string | null;
};

type Approval = {
  id: string;
  workflow_id?: string | null;
  workflow_run_id?: string | null;
  agent_run_id?: string | null;
  target_type: string;
  target_name: string;
  requested_by: string;
  requested_by_name?: string | null;
  required_role: string;
  risk_level: string;
  rationale?: string | null;
  plan_summary?: string | null;
  status: string;
  decided_by?: string | null;
  decided_by_name?: string | null;
  decided_at?: string | null;
};

type Run = {
  id: string;
  workflow_id: string;
  workflow_name: string;
  status: string;
  job_id?: string | null;
  gitops?: {
    job_id?: string | null;
    status?: string | null;
    commit_sha?: string | null;
    pr_url?: string | null;
    pipeline_id?: string | null;
    runtime_run_id?: string | null;
  } | null;
  params?: Record<string, unknown> | null;
  environment: string;
  created_at: string;
  requested_by?: string | null;
  requested_by_name?: string | null;
  approval_id?: string | null;
  approval_status?: string | null;
  approval_decided_by?: string | null;
  approval_decided_by_name?: string | null;
  approval_decided_at?: string | null;
};

type AgentRun = {
  id: string;
  goal: string;
  environment: string;
  status: string;
  requested_by: string;
  requested_by_name?: string | null;
  created_at: string;
  memory_used?: boolean;
  runtime?: {
    run_id?: string;
    status?: string | null;
    last_event_type?: string | null;
    updated_at?: string | null;
  } | null;
  evaluation?: {
    score: number;
    verdict: string;
    reasons: string[];
  } | null;
};

type AuditEvent = {
  id: string;
  event_type: string;
  outcome: string;
  source: string;
  actor_id: string;
  created_at: string;
  details: Record<string, unknown>;
};

type AgentConfig = {
  agent_type: string;
  api_url: string;
  model: string;
  api_key_ref?: string | null;
  source: string;
};

type MemoryResult = {
  id: string;
  score: number;
  text: string;
  metadata: Record<string, unknown>;
};

type EventIngest = {
  id: string;
  event_type: string;
  severity: string;
  summary: string;
  source: string;
  details?: Record<string, unknown>;
  environment: string;
  status: string;
  agent_run_id?: string | null;
  approval_id?: string | null;
  actions?: {
    plan_steps?: Array<{ title?: string; description?: string }>;
    tool_calls?: Array<{ tool?: string; action?: string }>;
    policy?: {
      allow: boolean;
      deny_reasons: string[];
      required_approvals: string[];
    };
    evaluation?: {
      score: number;
      verdict: string;
      reasons: string[];
    };
    approval?: { id?: string | null } | null;
    trail?: Array<{
      step: string;
      actor?: string;
      status?: string;
      timestamp?: string;
      details?: Record<string, unknown>;
    }>;
  };
  correlation_id?: string;
  received_at: string;
};

type RuntimeTimelineEvent = {
  event_id: string;
  event_type: string;
  schema_version: string;
  run_id: string;
  step_id?: string | null;
  timestamp: string;
  correlation_id: string;
  actor_id: string;
  tenant_id: string;
  agent_id: string;
  payload: Record<string, unknown>;
  visibility_level: "internal" | "tenant" | "public";
  redaction: "none" | "partial" | "full";
};

type ChatMessage = {
  id: string;
  role: string;
  content: string;
  tool_calls?: Record<string, unknown>;
  tool_results?: Record<string, unknown>;
  created_at: string;
};

type ChatHealth = {
  status: string;
  agent_runtime?: {
    status?: string;
    llm?: { status?: string; detail?: string };
  };
};

type ChatToolResult = {
  action?: string;
  status?: string;
  result?: unknown;
  detail?: unknown;
};

type ChatSession = {
  id: string;
  title: string;
  updated_at: string;
};

type IamStatus = {
  provider: string;
  configured: boolean;
  admin_url?: string | null;
  realm?: string | null;
};

type IamUser = {
  id: string;
  username?: string | null;
  email?: string | null;
  enabled?: boolean;
};

type IamRole = {
  id?: string | null;
  name?: string | null;
  description?: string | null;
};

export function App() {
  const apiBase = (import.meta.env.VITE_API_URL as string | undefined)?.trim() ?? "";
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [loading, setLoading] = useState(true);
  const [plugins, setPlugins] = useState<Plugin[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [agentRuns, setAgentRuns] = useState<AgentRun[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [agentConfigs, setAgentConfigs] = useState<AgentConfig[]>([]);
  const [agentConfigDrafts, setAgentConfigDrafts] = useState<Record<string, AgentConfig>>({});
  const [memoryResults, setMemoryResults] = useState<MemoryResult[]>([]);
  const [memorySearch, setMemorySearch] = useState({
    query: "",
    topK: "5",
    type: "",
    source: "",
    agentType: ""
  });
  const [events, setEvents] = useState<EventIngest[]>([]);
  const [chatSessions, setChatSessions] = useState<ChatSession[]>([]);
  const [chatSessionId, setChatSessionId] = useState<string | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatSessionEvents, setChatSessionEvents] = useState<EventIngest[]>([]);
  const [chatSessionEventsError, setChatSessionEventsError] = useState<string | null>(null);
  const [chatInput, setChatInput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [chatHealth, setChatHealth] = useState<ChatHealth | null>(null);
  const [iamStatus, setIamStatus] = useState<IamStatus | null>(null);
  const [iamUsers, setIamUsers] = useState<IamUser[]>([]);
  const [iamRoles, setIamRoles] = useState<IamRole[]>([]);
  const [userIamRoles, setUserIamRoles] = useState<string[]>([]);
  const [iamRoleSelections, setIamRoleSelections] = useState<Record<string, string>>({});
  const [auditFilters, setAuditFilters] = useState({
    source: "",
    eventType: "",
    actorId: "",
    outcome: "",
    since: "",
    until: ""
  });
  const [auditFilterDraft, setAuditFilterDraft] = useState({
    source: "",
    eventType: "",
    actorId: "",
    outcome: "",
    since: "",
    until: ""
  });
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const refreshPromiseRef = useRef<Promise<boolean> | null>(null);
  const chatThreadRef = useRef<HTMLDivElement | null>(null);
  const sessionActivityEndRef = useRef<HTMLDivElement | null>(null);

  const normalizeChatToolItems = (toolResults?: Record<string, unknown>): ChatToolResult[] => {
    if (!toolResults) {
      return [];
    }
    const items = (toolResults as { items?: unknown }).items;
    return Array.isArray(items) ? (items as ChatToolResult[]) : [];
  };

  const renderChatToolSummary = (item: ChatToolResult): string[] => {
    const action = item.action ?? "action";
    const status = item.status ?? "status";
    if (item.status && item.status !== "ok") {
      return [`${action}:${status}`];
    }
    const result = item.result;
    if (action === "plugin.list" && Array.isArray(result)) {
      const names = result
        .map((entry) => {
          if (!entry || typeof entry !== "object") return "";
          const record = entry as Record<string, unknown>;
          return String(record.name ?? record.id ?? "").trim();
        })
        .filter(Boolean)
        .join(", ");
      return [names ? `Plugins: ${names}` : "Plugins: none"];
    }
    if (action === "workflow.list" && Array.isArray(result)) {
      const names = result
        .map((entry) => {
          if (!entry || typeof entry !== "object") return "";
          const record = entry as Record<string, unknown>;
          return String(record.name ?? record.id ?? "").trim();
        })
        .filter(Boolean)
        .join(", ");
      return [names ? `Workflows: ${names}` : "Workflows: none"];
    }
    if (action === "approvals.list" && Array.isArray(result)) {
      if (!result.length) {
        return ["Approvals: none"];
      }
      return result
        .map((entry) => {
          if (!entry || typeof entry !== "object") return "";
          const record = entry as Record<string, unknown>;
          const id = String(record.id ?? "").trim();
          const workflowName = String(record.workflow_name ?? "").trim();
          const environment = String(record.environment ?? "").trim();
          const statusLabel = String(record.status ?? "").trim();
          const requestedBy = String(
            record.requested_by_name ?? record.requested_by ?? ""
          ).trim();
          const risk = String(record.risk_level ?? "").trim();
          const parts = [
            id ? `Approval ${id}` : "Approval",
            workflowName ? `workflow ${workflowName}` : "",
            environment ? `env ${environment}` : "",
            statusLabel ? `status ${statusLabel}` : "",
            requestedBy ? `requested by ${requestedBy}` : "",
            risk ? `risk ${risk}` : ""
          ].filter(Boolean);
          return parts.join(" · ");
        })
        .filter(Boolean);
    }
    if (action === "approval.get" && result && typeof result === "object") {
      const record = result as Record<string, unknown>;
      const id = String(record.id ?? "").trim();
      const workflow = String(record.workflow_name ?? "").trim();
      const env = String(record.environment ?? "").trim();
      const statusLabel = String(record.status ?? "").trim();
      const runStatus = String(record.run_status ?? "").trim();
      const requestedBy = String(
        record.requested_by_name ?? record.requested_by ?? ""
      ).trim();
      const risk = String(record.risk_level ?? "").trim();
      const summary = String(record.plan_summary ?? record.rationale ?? "").trim();
      const parts = [
        id ? `Approval ${id}` : "Approval detail",
        workflow ? `workflow ${workflow}` : "",
        env ? `env ${env}` : "",
        statusLabel ? `status ${statusLabel}` : "",
        runStatus ? `run ${runStatus}` : "",
        requestedBy ? `requested by ${requestedBy}` : "",
        risk ? `risk ${risk}` : ""
      ].filter(Boolean);
      const lines = [parts.join(" · ")];
      if (summary) {
        lines.push(summary);
      }
      return lines;
    }
    if (action === "approval.decision" && result && typeof result === "object") {
      const record = result as Record<string, unknown>;
      const approvalId = String(record.approval_id ?? "").trim();
      const decision = String(record.decision ?? "").trim();
      const statusLabel = String(record.status ?? "").trim();
      const workflow = String(record.workflow_name ?? "").trim();
      const runId = String(record.workflow_run_id ?? "").trim();
      const runStatus = String(record.run_status ?? "").trim();
      const jobId = String(record.job_id ?? "").trim();
      const environment = String(record.environment ?? "").trim();
      const parts = [
        approvalId ? `Approval ${approvalId}` : "Approval decision",
        decision ? `decision ${decision}` : "",
        statusLabel ? `status ${statusLabel}` : "",
        workflow ? `workflow ${workflow}` : "",
        environment ? `env ${environment}` : "",
        runId ? `run ${runId}` : "",
        runStatus ? `run status ${runStatus}` : "",
        jobId ? `job ${jobId}` : ""
      ].filter(Boolean);
      return [parts.join(" · ")];
    }
    if (action === "runs.list" && Array.isArray(result)) {
      const names = result
        .map((entry) => {
          if (!entry || typeof entry !== "object") return "";
          const record = entry as Record<string, unknown>;
          return String(record.workflow_id ?? record.id ?? "").trim();
        })
        .filter(Boolean)
        .join(", ");
      return [names ? `Runs: ${names}` : "Runs: none"];
    }
    if (action === "run.get" && result && typeof result === "object") {
      const record = result as Record<string, unknown>;
      const id = String(record.id ?? "").trim();
      const workflow = String(record.workflow_name ?? "").trim();
      const env = String(record.environment ?? "").trim();
      const statusLabel = String(record.status ?? "").trim();
      const jobId = String(record.job_id ?? "").trim();
      const approvalStatus = String(record.approval_status ?? "").trim();
      const requestedBy = String(
        record.requested_by_name ?? record.requested_by ?? ""
      ).trim();
      const paramKeys = Array.isArray(record.param_keys)
        ? record.param_keys.map((item) => String(item)).filter(Boolean)
        : [];
      const parts = [
        id ? `Run ${id}` : "Run detail",
        workflow ? `workflow ${workflow}` : "",
        env ? `env ${env}` : "",
        statusLabel ? `status ${statusLabel}` : "",
        jobId ? `job ${jobId}` : "",
        approvalStatus ? `approval ${approvalStatus}` : "",
        requestedBy ? `requested by ${requestedBy}` : ""
      ].filter(Boolean);
      const lines = [parts.join(" · ")];
      if (paramKeys.length) {
        lines.push(`Params: ${paramKeys.join(", ")}`);
      }
      return lines;
    }
    if (action === "events.list" && Array.isArray(result)) {
      const names = result
        .map((entry) => {
          if (!entry || typeof entry !== "object") return "";
          const record = entry as Record<string, unknown>;
          return String(record.event_type ?? record.id ?? "").trim();
        })
        .filter(Boolean)
        .join(", ");
      return [names ? `Events: ${names}` : "Events: none"];
    }
    if (action === "audit.list" && Array.isArray(result)) {
      return [result.length ? `Audit events: ${result.length}` : "Audit events: none"];
    }
    if (action === "workflow.run" && result && typeof result === "object") {
      const record = result as Record<string, unknown>;
      const status = String(record.status ?? "").trim();
      const runId = String(record.run_id ?? "").trim();
      return [`Run: ${runId || "unknown"} ${status || ""}`.trim()];
    }
    if (action === "agent.plan" && result && typeof result === "object") {
      const record = result as Record<string, unknown>;
      const planId = String(record.plan_id ?? "").trim();
      return [planId ? `Plan created: ${planId}` : "Plan created"];
    }
    return [`${action}:${status}`];
  };
  const normalizeStatusClass = (value: string) =>
    value
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  const normalizeEventStatus = (status: string) => {
    const value = status.trim().toLowerCase();
    if (!value) return "Running";
    if (
      value.includes("failed") ||
      value.includes("error") ||
      value.includes("deny") ||
      value.includes("reject") ||
      value.includes("abort")
    ) {
      return "Failed";
    }
    if (
      value.includes("success") ||
      value.includes("succeed") ||
      value.includes("completed") ||
      value.includes("approved") ||
      value.includes("allow")
    ) {
      return "Success";
    }
    if (
      value.includes("pending") ||
      value.includes("queued") ||
      value.includes("waiting")
    ) {
      return "Pending";
    }
    return "Running";
  };
  const mapEventTypeLabel = (eventType: string) => {
    const value = eventType.trim().toLowerCase();
    if (value.startsWith("workflow.") || value.startsWith("run.")) return "WorkflowTriggered";
    if (value.startsWith("policy.")) return "PolicyDecision";
    if (value.startsWith("agent.") || value.startsWith("chat.")) return "AgentAction";
    if (value.startsWith("tool.call.")) return "ToolCall";
    if (value.startsWith("action.execution.")) return "ExecutionResult";
    return eventType;
  };
  const extractEventActorId = (event: EventIngest) => {
    const details =
      event.details && typeof event.details === "object"
        ? (event.details as Record<string, unknown>)
        : {};
    const payload =
      details.payload && typeof details.payload === "object"
        ? (details.payload as Record<string, unknown>)
        : {};
    const direct = String(details.actor_id ?? "").trim();
    if (direct) return direct;
    const payloadActor = String(payload.actor_id ?? "").trim();
    if (payloadActor) return payloadActor;
    const requestedBy = String(details.requested_by ?? "").trim();
    if (requestedBy) return requestedBy;
    return "";
  };
  const extractEventSessionId = (event: EventIngest) => {
    const details =
      event.details && typeof event.details === "object"
        ? (event.details as Record<string, unknown>)
        : {};
    return String(details.session_id ?? "").trim();
  };
  const extractEventError = (event: EventIngest) => {
    const details =
      event.details && typeof event.details === "object"
        ? (event.details as Record<string, unknown>)
        : {};
    const payload =
      details.payload && typeof details.payload === "object"
        ? (details.payload as Record<string, unknown>)
        : {};
    const directError = details.error;
    if (typeof directError === "string" && directError.trim()) return directError.trim();
    const payloadError = payload.error;
    if (typeof payloadError === "string" && payloadError.trim()) return payloadError.trim();
    return null;
  };
  const mergeRuntimeTimelineEvents = (
    current: RuntimeTimelineEvent[],
    incoming: RuntimeTimelineEvent[]
  ) => {
    const merged = [...current];
    const seen = new Set(current.map((event) => event.event_id));
    incoming.forEach((event) => {
      if (!seen.has(event.event_id)) {
        merged.push(event);
        seen.add(event.event_id);
      }
    });
    return merged.sort((a, b) => {
      const left = new Date(a.timestamp).getTime();
      const right = new Date(b.timestamp).getTime();
      if (left !== right) return left - right;
      return a.event_id.localeCompare(b.event_id);
    });
  };
  const runtimeEventHeadline = (event: RuntimeTimelineEvent) => {
    const payload = event.payload ?? {};
    if (event.event_type === "policy.decision.recorded") {
      const outcome = String(payload.outcome ?? "unknown");
      return `Policy decision: ${outcome}`;
    }
    if (event.event_type.startsWith("tool.call.")) {
      const plugin = String(payload.plugin ?? "plugin");
      const action = String(payload.action ?? "action");
      return `${event.event_type} · ${plugin}:${action}`;
    }
    if (event.event_type === "approval.requested") return "Approval requested";
    if (event.event_type === "approval.resolved") {
      const decision = String(payload.decision ?? "resolved");
      return `Approval ${decision}`;
    }
    return event.event_type;
  };
  const matchesSearch = (value: string, query: string) =>
    value.toLowerCase().includes(query.toLowerCase());
  const renderInlineChatText = (text: string) => {
    const segments = text.split(/(`[^`]+`)/g);
    return segments.map((segment, index) => {
      if (segment.startsWith("`") && segment.endsWith("`")) {
        return (
          <code key={`${segment}-${index}`} className="inline-code">
            {segment.slice(1, -1)}
          </code>
        );
      }
      return <span key={`${segment}-${index}`}>{segment}</span>;
    });
  };
  const renderChatTextBlock = (text: string) =>
    text
      .split(/\n{2,}/)
      .filter((block) => block.trim().length > 0)
      .map((block, index) => {
        const lines = block.split("\n");
        return (
          <p key={`${block}-${index}`} className="chat-paragraph">
            {lines.map((line, lineIndex) => (
              <span key={`${line}-${lineIndex}`}>
                {renderInlineChatText(line)}
                {lineIndex < lines.length - 1 ? <br /> : null}
              </span>
            ))}
          </p>
        );
      });
  const renderChatCodeBlock = (code: string, language?: string) => (
    <div className="chat-code">
      <div className="chat-code-header">{language || "code"}</div>
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
  const renderChatContent = (content: string) => {
    const trimmed = content.trim();
    if (trimmed) {
      const isJsonCandidate = trimmed.startsWith("{") || trimmed.startsWith("[");
      if (isJsonCandidate) {
        try {
          const parsed = JSON.parse(trimmed);
          return renderChatCodeBlock(JSON.stringify(parsed, null, 2), "json");
        } catch {
          // Fall back to markdown-like rendering.
        }
      }
      const isYamlCandidate =
        trimmed.startsWith("---") ||
        (/^[A-Za-z0-9_-]+:\s/m.test(trimmed) && trimmed.includes("\n"));
      if (isYamlCandidate) {
        return renderChatCodeBlock(trimmed, "yaml");
      }
    }

    const fencedParts = content.split(/```/g);
    return fencedParts.map((part, index) => {
      if (index % 2 === 1) {
        const lines = part.split("\n");
        const lang = lines[0]?.trim();
        const code = lines.slice(lang ? 1 : 0).join("\n");
        return (
          <div key={`${index}-code`}>{renderChatCodeBlock(code, lang || undefined)}</div>
        );
      }
      return (
        <div key={`${index}-text`} className="chat-text">
          {renderChatTextBlock(part)}
        </div>
      );
    });
  };
  const hasPermission = (permission: string) => {
    if (!auth) return false;
    if (auth.permissions.includes(permission)) return true;
    const prefix = permission.split(":")[0];
    return auth.permissions.includes(`${prefix}:*`);
  };
  const [pluginForm, setPluginForm] = useState({
    name: "",
    endpoint: "",
    version: "v1",
    plugin_type: "workflow",
    auth_type: "none",
    auth_ref: "",
    auth_config: "{}",
    actions: "{}"
  });
  const [workflowForm, setWorkflowForm] = useState({
    name: "",
    description: "",
    pluginId: "",
    action: "",
    input_schema: ""
  });
  const [activeView, setActiveView] = useState("home");
  const [workflowSearch, setWorkflowSearch] = useState("");
  const [workflowRunNotice, setWorkflowRunNotice] = useState<WorkflowRunNotice | null>(null);
  const [focusRunId, setFocusRunId] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<Run | null>(null);
  const [selectedAgentRun, setSelectedAgentRun] = useState<AgentRun | null>(null);
  const [runtimeTimeline, setRuntimeTimeline] = useState<RuntimeTimelineEvent[]>([]);
  const [runtimeTimelineLoading, setRuntimeTimelineLoading] = useState(false);
  const [runtimeTimelineError, setRuntimeTimelineError] = useState<string | null>(null);
  const [pluginSearch, setPluginSearch] = useState("");
  const [eventSearch, setEventSearch] = useState("");
  const [pluginEditingId, setPluginEditingId] = useState<string | null>(null);
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({});
  const [eventsLive, setEventsLive] = useState(true);
  const [eventsStreamError, setEventsStreamError] = useState<string | null>(null);
  const [runParamsByWorkflow, setRunParamsByWorkflow] = useState<Record<string, string>>({});
  const [runEnvByWorkflow, setRunEnvByWorkflow] = useState<Record<string, string>>({});
  const [agentRunForm, setAgentRunForm] = useState({
    goal: "",
    environment: "dev",
    tools: "plugin_gateway.invoke",
    documents: ""
  });

  const getRequiredFields = (schema?: WorkflowInputSchema | null) => {
    if (!schema?.required) return [];
    return schema.required.map((field) => field.trim()).filter(Boolean);
  };

  const schemaTypeMatches = (expected: string, value: unknown) => {
    if (expected === "string") return typeof value === "string";
    if (expected === "number") return typeof value === "number" && Number.isFinite(value);
    if (expected === "integer") return typeof value === "number" && Number.isInteger(value);
    if (expected === "boolean") return typeof value === "boolean";
    if (expected === "object") return typeof value === "object" && value !== null && !Array.isArray(value);
    if (expected === "array") return Array.isArray(value);
    return true;
  };

  const validateWorkflowParams = (workflow: Workflow, params: Record<string, unknown>) => {
    const schema = workflow.input_schema ?? undefined;
    if (!schema) return null;
    const required = getRequiredFields(schema);
    const missing = required.filter((field) => !(field in params));
    if (missing.length) {
      return `Missing required fields: ${missing.join(", ")}`;
    }
    if (schema.properties) {
      for (const field of required) {
        const expectedType = schema.properties[field]?.type;
        if (expectedType && !schemaTypeMatches(expectedType, params[field])) {
          return `Field ${field} must be ${expectedType}`;
        }
      }
    }
    return null;
  };

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2500);

    const loadAuth = async () => {
      try {
        const response = await apiFetch(`${apiBase}/v1/auth/me`, {
          signal: controller.signal
        });
        if (response.ok && active) {
          const data = (await response.json()) as AuthState;
          setAuth(data);
        } else if (response.status === 401 && active) {
          setAuth(null);
          showStatus("Session expired. Please log in again.");
        }
      } catch {
        // Fall through to render the unauthenticated state.
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };
    void loadAuth();

    return () => {
      active = false;
      clearTimeout(timeoutId);
      controller.abort();
    };
  }, [apiBase]);

  useEffect(() => {
    if (!auth) {
      return;
    }
    const loadAudit = async () => {
      const params = new URLSearchParams();
      if (auditFilters.source) params.set("source", auditFilters.source);
      if (auditFilters.eventType) params.set("event_type", auditFilters.eventType);
      if (auditFilters.actorId) params.set("actor_id", auditFilters.actorId);
      if (auditFilters.outcome) params.set("outcome", auditFilters.outcome);
      if (auditFilters.since) params.set("since", auditFilters.since);
      if (auditFilters.until) params.set("until", auditFilters.until);
      const url = `${apiBase}/v1/audit${params.toString() ? `?${params.toString()}` : ""}`;
      const auditResponse = await apiFetch(url);
      if (auditResponse.ok) {
        const data = (await auditResponse.json()) as AuditEvent[];
        setAuditEvents(data);
      }
    };

    const loadData = async () => {
      try {
        const [
          pluginsResponse,
          workflowsResponse,
          approvalsResponse,
          runsResponse,
          agentConfigsResponse,
          agentRunsResponse,
          eventsResponse,
          chatSessionsResponse,
          iamStatusResponse,
          iamUsersResponse,
          iamRolesResponse
        ] = await Promise.all([
          apiFetch(`${apiBase}/v1/plugins`),
          apiFetch(`${apiBase}/v1/workflows`),
          apiFetch(`${apiBase}/v1/approvals`),
          apiFetch(`${apiBase}/v1/runs`),
          apiFetch(`${apiBase}/v1/agent/configs`),
          apiFetch(`${apiBase}/v1/agent/runs`),
          apiFetch(`${apiBase}/v1/events`),
          apiFetch(`${apiBase}/v1/chat/sessions`),
          hasPermission("iam:read")
            ? apiFetch(`${apiBase}/v1/iam/status`)
            : Promise.resolve({ ok: false, json: async () => ({}) }),
          hasPermission("iam:read")
            ? apiFetch(`${apiBase}/v1/iam/users`)
            : Promise.resolve({ ok: false, json: async () => ({}) }),
          hasPermission("iam:read")
            ? apiFetch(`${apiBase}/v1/iam/roles`)
            : Promise.resolve({ ok: false, json: async () => ({}) })
        ]);
        if (pluginsResponse.ok) {
          const data = (await pluginsResponse.json()) as Plugin[];
          setPlugins(data);
        }
        if (workflowsResponse.ok) {
          const data = (await workflowsResponse.json()) as Workflow[];
          setWorkflows(data);
        }
        if (approvalsResponse.ok) {
          const data = (await approvalsResponse.json()) as Approval[];
          setApprovals(data);
        }
        if (runsResponse.ok) {
          const data = (await runsResponse.json()) as Run[];
          setRuns(data);
        }
        if (agentConfigsResponse.ok) {
          const data = (await agentConfigsResponse.json()) as AgentConfig[];
          setAgentConfigs(data);
          const drafts = data.reduce<Record<string, AgentConfig>>((acc, cfg) => {
            acc[cfg.agent_type] = { ...cfg };
            return acc;
          }, {});
          setAgentConfigDrafts(drafts);
        }
        if (agentRunsResponse.ok) {
          const data = (await agentRunsResponse.json()) as AgentRun[];
          setAgentRuns(data);
        }
        if (eventsResponse.ok) {
          const data = (await eventsResponse.json()) as EventIngest[];
          setEvents(data);
        }
        if (chatSessionsResponse.ok) {
          const data = (await chatSessionsResponse.json()) as ChatSession[];
          setChatSessions(data);
          if (!chatSessionId && data.length > 0) {
            setChatSessionId(data[0].id);
          }
        }
        if (iamStatusResponse.ok) {
          const data = (await iamStatusResponse.json()) as IamStatus;
          setIamStatus(data);
        }
        if (iamUsersResponse.ok) {
          const data = (await iamUsersResponse.json()) as IamUser[];
          setIamUsers(data);
        }
        if (iamRolesResponse.ok) {
          const data = (await iamRolesResponse.json()) as IamRole[];
          setIamRoles(data);
        }
        await loadAudit();
      } catch {
        setStatusMessage("Unable to load registry data.");
      }
    };
    void loadData();
  }, [auth, apiBase, auditFilters]);

  useEffect(() => {
    if (!auth || !hasPermission("iam:read") || !auth.actor_id) {
      setUserIamRoles([]);
      return;
    }
    let active = true;
    const controller = new AbortController();
    const loadRoles = async () => {
      try {
        const response = await apiFetch(`${apiBase}/v1/iam/users/${auth.actor_id}/roles`, {
          signal: controller.signal
        });
        if (!response.ok || !active) {
          return;
        }
        const data = (await response.json()) as IamRole[];
        const names = data
          .map((role) => role.name ?? "")
          .map((name) => name.trim())
          .filter(Boolean);
        setUserIamRoles(names);
      } catch {
        if (active) {
          setUserIamRoles([]);
        }
      }
    };
    void loadRoles();
    return () => {
      active = false;
      controller.abort();
    };
  }, [apiBase, auth]);

  useEffect(() => {
    if (!auth || activeView !== "events") {
      return;
    }
    let active = true;
    const loadEvents = async () => {
      try {
        const response = await apiFetch(`${apiBase}/v1/events`);
        if (!active) {
          return;
        }
        if (response.ok) {
          const data = (await response.json()) as EventIngest[];
          setEvents(data);
          setEventsStreamError(null);
          return;
        }
        setEventsStreamError(`Failed to load events (${response.status}).`);
      } catch {
        if (active) {
          setEventsStreamError("Failed to load events.");
        }
      }
    };
    void loadEvents();
    return () => {
      active = false;
    };
  }, [activeView, apiBase, auth]);

  useEffect(() => {
    if (!auth || activeView !== "events" || !eventsLive) {
      return;
    }
    if (typeof EventSource === "undefined") {
      return;
    }
    const since = new Date(Date.now() - 15 * 60 * 1000).toISOString();
    const baseUrl = apiBase || "";
    const streamUrl = `${baseUrl}/v1/events/stream?since=${encodeURIComponent(since)}`;
    const source = new EventSource(streamUrl, { withCredentials: true });
    source.onmessage = (event) => {
      if (!event.data) {
        return;
      }
      try {
        const payload = JSON.parse(event.data) as EventIngest;
        setEvents((current) => {
          if (current.some((item) => item.id === payload.id)) {
            return current;
          }
          return [payload, ...current];
        });
      } catch {
        setEventsStreamError("Failed to parse event stream.");
      }
    };
    source.onerror = () => {
      setEventsStreamError("Event stream disconnected.");
      source.close();
    };
    return () => {
      source.close();
    };
  }, [activeView, apiBase, auth, eventsLive]);

  useEffect(() => {
    if (!auth || (!selectedRun && !selectedAgentRun)) {
      setRuntimeTimeline([]);
      setRuntimeTimelineLoading(false);
      setRuntimeTimelineError(null);
      return;
    }
    let active = true;
    let source: EventSource | null = null;
    const runtimeRunId =
      selectedRun &&
      typeof selectedRun.gitops?.runtime_run_id === "string" &&
      selectedRun.gitops.runtime_run_id.trim()
        ? selectedRun.gitops.runtime_run_id.trim()
        : selectedRun?.id ?? selectedAgentRun?.id ?? "";
    const fallbackRunId = selectedRun?.id ?? selectedAgentRun?.id ?? runtimeRunId;
    setRuntimeTimeline([]);
    setRuntimeTimelineLoading(true);
    setRuntimeTimelineError(null);

    const normalizeRuntimeEvent = (record: Record<string, unknown>): RuntimeTimelineEvent | null => {
      const eventId = String(record.event_id ?? "").trim();
      const eventType = String(record.event_type ?? "").trim();
      if (!eventId || !eventType) {
        return null;
      }
      return {
        event_id: eventId,
        event_type: eventType,
        schema_version: String(record.schema_version ?? "v1"),
        run_id: String(record.run_id ?? fallbackRunId),
        step_id: record.step_id ? String(record.step_id) : null,
        timestamp: String(record.timestamp ?? new Date().toISOString()),
        correlation_id: String(record.correlation_id ?? ""),
        actor_id: String(record.actor_id ?? ""),
        tenant_id: String(record.tenant_id ?? ""),
        agent_id: String(record.agent_id ?? ""),
        payload:
          record.payload && typeof record.payload === "object"
            ? (record.payload as Record<string, unknown>)
            : {},
        visibility_level: "tenant",
        redaction: "none"
      };
    };

    const pushRuntimeEvents = (events: unknown[]) => {
      const parsed = events
        .map((entry) =>
          entry && typeof entry === "object"
            ? normalizeRuntimeEvent(entry as Record<string, unknown>)
            : null
        )
        .filter((entry): entry is RuntimeTimelineEvent => entry !== null);
      if (parsed.length) {
        setRuntimeTimeline((current) => mergeRuntimeTimelineEvents(current, parsed));
      }
    };

    const knownEventTypes = [
      "run.started",
      "plan.step.proposed",
      "agent.message.sent",
      "policy.decision.recorded",
      "approval.requested",
      "approval.resolved",
      "tool.call.started",
      "tool.call.retrying",
      "tool.call.completed",
      "tool.call.failed",
      "run.succeeded",
      "run.failed",
      "run.aborted"
    ];

    const load = async () => {
      try {
        const timelineUrl = `${apiBase}/v1/runs/${encodeURIComponent(runtimeRunId)}/timeline?limit=500`;
        const response = await apiFetch(timelineUrl);
        if (!active) return;
        if (!response.ok) {
          setRuntimeTimelineError(
            response.status === 404
              ? "No v1 runtime timeline found for this run."
              : "Failed to load runtime timeline."
          );
          return;
        }
        const payload = (await response.json()) as {
          events?: unknown;
          next_event_id?: unknown;
        };
        const events = Array.isArray(payload?.events) ? payload.events : [];
        pushRuntimeEvents(events);
        if (typeof EventSource === "undefined") {
          return;
        }
        const cursor =
          typeof payload?.next_event_id === "string" ? payload.next_event_id.trim() : "";
        const params = new URLSearchParams({
          follow_seconds: "10",
          poll_interval_seconds: "1.0"
        });
        if (cursor) {
          params.set("last_event_id", cursor);
        }
        const streamUrl = `${apiBase}/v1/runs/${encodeURIComponent(runtimeRunId)}/stream?${params.toString()}`;
        source = new EventSource(streamUrl, { withCredentials: true });

        knownEventTypes.forEach((eventType) => {
          source?.addEventListener(eventType, (evt) => {
            if (!active) return;
            try {
              const data = JSON.parse((evt as MessageEvent).data) as unknown;
              if (data && typeof data === "object") {
                pushRuntimeEvents([data]);
              }
            } catch {
              setRuntimeTimelineError("Failed to parse runtime stream event.");
            }
          });
        });

        source.onmessage = (evt) => {
          if (!active) return;
          try {
            const data = JSON.parse(evt.data) as unknown;
            if (data && typeof data === "object") {
              pushRuntimeEvents([data]);
            }
          } catch {
            setRuntimeTimelineError("Failed to parse runtime stream payload.");
          }
        };

        source.onerror = () => {
          if (!active) return;
          setRuntimeTimelineError("Runtime stream disconnected.");
        };
      } catch {
        if (active) {
          setRuntimeTimelineError("Failed to load runtime timeline.");
        }
      } finally {
        if (active) {
          setRuntimeTimelineLoading(false);
        }
      }
    };

    void load();
    return () => {
      active = false;
      source?.close();
    };
  }, [apiBase, auth, selectedAgentRun, selectedRun]);

  useEffect(() => {
    if (!auth || activeView !== "chat") {
      return;
    }
    let active = true;
    const loadChatHealth = async () => {
      try {
        const response = await apiFetch(`${apiBase}/v1/chat/health`);
        if (!response.ok || !active) {
          setChatHealth({ status: "unavailable" });
          return;
        }
        const data = (await response.json()) as ChatHealth;
        if (active) {
          setChatHealth(data);
        }
      } catch {
        if (active) {
          setChatHealth({ status: "unavailable" });
        }
      }
    };
    void loadChatHealth();
    const intervalId = window.setInterval(loadChatHealth, 30000);
    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, [activeView, apiBase, auth]);

  useEffect(() => {
    if (!auth || activeView !== "chat" || !chatSessionId) {
      setChatSessionEvents([]);
      setChatSessionEventsError(null);
      return;
    }
    let active = true;
    let source: EventSource | null = null;
    let reconnectTimer: number | null = null;
    let pollTimer: number | null = null;
    let streamSince = new Date(Date.now() - 15 * 60 * 1000).toISOString();
    const pushEvent = (payload: EventIngest) => {
      setChatSessionEvents((current) => {
        if (current.some((item) => item.id === payload.id)) {
          return current;
        }
        return [...current, payload];
      });
      if (payload.received_at) {
        const ts = new Date(payload.received_at);
        if (!Number.isNaN(ts.getTime())) {
          streamSince = ts.toISOString();
        }
      }
    };
    const mergeEvents = (incoming: EventIngest[]) => {
      setChatSessionEvents((current) => {
        const merged = [...current];
        const seen = new Set(current.map((item) => item.id));
        incoming.forEach((item) => {
          if (!seen.has(item.id)) {
            merged.push(item);
            seen.add(item.id);
          }
        });
        return merged;
      });
      incoming.forEach((item) => {
        if (item.received_at) {
          const ts = new Date(item.received_at);
          if (!Number.isNaN(ts.getTime())) {
            streamSince = ts > new Date(streamSince) ? ts.toISOString() : streamSince;
          }
        }
      });
    };
    const pollEvents = async () => {
      try {
        const response = await apiFetch(`${apiBase}/v1/events`);
        if (!active || !response.ok) {
          return;
        }
        const data = (await response.json()) as EventIngest[];
        mergeEvents(data);
      } catch {
        return;
      }
    };
    const scheduleReconnect = () => {
      if (!active || reconnectTimer !== null) {
        return;
      }
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        if (!active) return;
        connectStream();
      }, 1500);
    };
    const connectStream = () => {
      if (!active || typeof EventSource === "undefined") {
        return;
      }
      const streamUrl = `${apiBase}/v1/events/stream?since=${encodeURIComponent(streamSince)}`;
      source = new EventSource(streamUrl, { withCredentials: true });
      source.onmessage = (event) => {
        if (!event.data) return;
        try {
          const payload = JSON.parse(event.data) as EventIngest;
          pushEvent(payload);
          setChatSessionEventsError(null);
        } catch {
          setChatSessionEventsError("Failed to parse session activity stream.");
        }
      };
      source.onerror = () => {
        setChatSessionEventsError("Session activity stream reconnecting...");
        source?.close();
        source = null;
        scheduleReconnect();
      };
    };
    const load = async () => {
      try {
        const response = await apiFetch(`${apiBase}/v1/events`);
        if (!active) return;
        if (!response.ok) {
          setChatSessionEventsError(`Failed to load session activity (${response.status}).`);
          return;
        }
        const data = (await response.json()) as EventIngest[];
        if (!active) return;
        setChatSessionEvents(data);
        setChatSessionEventsError(null);
        mergeEvents(data);
        connectStream();
        pollTimer = window.setInterval(() => {
          void pollEvents();
        }, 5000);
      } catch {
        if (active) {
          setChatSessionEventsError("Failed to load session activity.");
        }
      }
    };
    void load();
    return () => {
      active = false;
      source?.close();
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
      }
      if (pollTimer !== null) {
        window.clearInterval(pollTimer);
      }
    };
  }, [activeView, apiBase, auth, chatSessionId]);

  useEffect(() => {
    if (activeView !== "chat") {
      return;
    }
    const marker = sessionActivityEndRef.current;
    if (marker && typeof marker.scrollIntoView === "function") {
      marker.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [activeView, chatSessionEvents]);

  useEffect(() => {
    if (activeView !== "chat") {
      return;
    }
    const thread = chatThreadRef.current;
    if (!thread) {
      return;
    }
    if (typeof thread.scrollTo === "function") {
      thread.scrollTo({ top: thread.scrollHeight, behavior: "smooth" });
      return;
    }
    thread.scrollTop = thread.scrollHeight;
  }, [activeView, chatMessages, chatSessionId]);

  useEffect(() => {
    if (!auth || !workflowRunNotice?.runId) {
      return;
    }
    let active = true;
    let attempts = 0;
    const maxAttempts = 60;
    const poll = async () => {
      attempts += 1;
      try {
        const response = await apiFetch(`${apiBase}/v1/runs?limit=200`);
        if (!response.ok || !active) {
          return;
        }
        const data = (await response.json()) as Run[];
        if (!active) {
          return;
        }
        setRuns(data);
        const match = data.find((run) => run.id === workflowRunNotice.runId);
        if (!match) {
          return;
        }
        setWorkflowRunNotice((current) => {
          if (!current || current.runId !== match.id) {
            return current;
          }
          const nextOutcome = mapRunOutcome(match.status, match.approval_status);
          return {
            ...current,
            outcome: nextOutcome,
            status: match.status,
            jobId: match.job_id ?? current.jobId,
            approvalId: match.approval_id ?? current.approvalId,
            approvalStatus: match.approval_status ?? current.approvalStatus
          };
        });
        if (isTerminalRunStatus(match.status) || attempts >= maxAttempts) {
          active = false;
        }
      } catch {
        return;
      }
    };
    const interval = window.setInterval(poll, 5000);
    void poll();
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [apiBase, auth, workflowRunNotice?.runId]);

  useEffect(() => {
    if (activeView !== "workflows" || !focusRunId) {
      return;
    }
    const targetId = focusRunId;
    const timeoutId = window.setTimeout(() => {
      const element = document.getElementById(`run-row-${targetId}`);
      if (element) {
        element.scrollIntoView({ behavior: "smooth", block: "center" });
        element.classList.add("run-row--highlight");
        window.setTimeout(() => element.classList.remove("run-row--highlight"), 1600);
      }
      setFocusRunId(null);
    }, 60);
    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [activeView, focusRunId, runs]);

  const showStatus = (message: string) => {
    setStatusMessage(message);
    setTimeout(() => setStatusMessage(null), 4000);
  };

  const parseErrorDetail = async (response: Response) => {
    try {
      const payload = (await response.json()) as
        | { detail?: unknown; message?: unknown; error?: unknown }
        | string;
      if (typeof payload === "string") {
        return payload;
      }
      if (payload && typeof payload === "object") {
        const detail = payload.detail ?? payload.message ?? payload.error;
        if (typeof detail === "string") {
          return detail;
        }
        if (Array.isArray(detail)) {
          return detail.map((item) => String(item)).join(", ");
        }
      }
    } catch {
      return null;
    }
    return null;
  };

  const isTerminalRunStatus = (status: string) =>
    [
      "succeeded",
      "success",
      "completed",
      "failed",
      "error",
      "cancelled",
      "canceled",
      "rejected",
      "denied"
    ].includes(status.toLowerCase().trim());

  const isSuccessRunStatus = (status: string) =>
    ["succeeded", "success", "completed"].includes(status.toLowerCase().trim());

  const mapRunOutcome = (status: string, approvalStatus?: string | null) => {
    const normalized = status.toLowerCase().trim();
    if (approvalStatus?.toLowerCase().trim() === "pending") {
      return "pending";
    }
    if (normalized.includes("pending")) {
      return "pending";
    }
    if (normalized.includes("fail") || normalized.includes("error") || normalized.includes("deny")) {
      return "failed";
    }
    return "submitted";
  };

  const mapRunStatusBadge = (status: string, approvalStatus?: string | null) => {
    const normalized = status.toLowerCase().trim();
    if (approvalStatus?.toLowerCase().trim() === "pending") {
      return "status-badge--pending-approval";
    }
    if (normalized.includes("success") || normalized.includes("succeeded") || normalized.includes("completed")) {
      return "status-badge--success";
    }
    if (normalized.includes("fail") || normalized.includes("error") || normalized.includes("deny")) {
      return "status-badge--failed";
    }
    if (normalized.includes("pending")) {
      return "status-badge--pending-approval";
    }
    if (normalized.includes("submitted")) {
      return "status-badge--submitted";
    }
    return "status-badge--neutral";
  };

  const getCookie = (name: string) => {
    const prefix = `${name}=`;
    return document.cookie
      .split(";")
      .map((cookie) => cookie.trim())
      .find((cookie) => cookie.startsWith(prefix))
      ?.slice(prefix.length);
  };

  const refreshSession = async () => {
    if (refreshPromiseRef.current) {
      return refreshPromiseRef.current;
    }
    const csrf = getCookie("autonoma_csrf") ?? "";
    const refreshPromise = fetch(`${apiBase}/v1/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: csrf ? { "x-csrf-token": csrf } : undefined
    })
      .then((response) => response.ok)
      .catch(() => false)
      .finally(() => {
        refreshPromiseRef.current = null;
      });
    refreshPromiseRef.current = refreshPromise;
    return refreshPromise;
  };

  const apiFetch = async (
    input: RequestInfo | URL,
    init?: RequestInit,
    allowRetry: boolean = true
  ) => {
    const response = await fetch(input, { credentials: "include", ...init });
    if (!allowRetry || response.status !== 401) {
      return response;
    }
    if (typeof input === "string" && input.includes("/v1/auth/refresh")) {
      return response;
    }
    const refreshed = await refreshSession();
    if (!refreshed) {
      setAuth(null);
      showStatus("Session expired. Please log in again.");
      return response;
    }
    return fetch(input, { credentials: "include", ...init });
  };

  const canWriteAgentConfigs =
    auth?.permissions.includes("agent:config:write") || auth?.permissions.includes("agent:*");
  const canRunAgents = auth?.permissions.includes("agent:run") || auth?.permissions.includes("agent:*");
  const canReadMemory =
    auth?.permissions.includes("memory:read") || auth?.permissions.includes("memory:*");

  const handleUpdateAgentConfig = async (agentType: string) => {
    const draft = agentConfigDrafts[agentType];
    if (!draft) {
      return;
    }
    const response = await apiFetch(`${apiBase}/v1/agent/configs/${agentType}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        api_url: draft.api_url,
        model: draft.model,
        api_key_ref: draft.api_key_ref
      })
    });
    if (!response.ok) {
      showStatus("Config update failed.");
      return;
    }
    const updated = (await response.json()) as AgentConfig;
    setAgentConfigs((current) =>
      current.map((cfg) => (cfg.agent_type === updated.agent_type ? updated : cfg))
    );
    setAgentConfigDrafts((current) => ({ ...current, [updated.agent_type]: updated }));
    showStatus("Agent config updated.");
  };

  const resetPluginForm = () => {
    setPluginForm({
      name: "",
      endpoint: "",
      version: "v1",
      plugin_type: "workflow",
      auth_type: "none",
      auth_ref: "",
      auth_config: "{}",
      actions: "{}"
    });
    setPluginEditingId(null);
  };

  const handleRegisterPlugin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const editing = pluginEditingId !== null;
    let actions: Record<string, unknown> = {};
    let authConfig: Record<string, unknown> = {};
    try {
      actions = pluginForm.actions ? (JSON.parse(pluginForm.actions) as Record<string, unknown>) : {};
      authConfig = pluginForm.auth_config
        ? (JSON.parse(pluginForm.auth_config) as Record<string, unknown>)
        : {};
    } catch {
      showStatus("Plugin actions must be valid JSON.");
      return;
    }
    const endpoint = editing
      ? `${apiBase}/v1/plugins/${pluginEditingId}`
      : `${apiBase}/v1/plugins`;
    const method = editing ? "PUT" : "POST";
    const response = await apiFetch(endpoint, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: pluginForm.name,
        endpoint: pluginForm.endpoint,
        version: pluginForm.version,
        plugin_type: pluginForm.plugin_type,
        auth_type: pluginForm.auth_type,
        auth_ref: pluginForm.auth_ref || null,
        auth_config: authConfig,
        actions
      })
    });
    if (!response.ok) {
      showStatus(editing ? "Failed to update plugin." : "Failed to register plugin.");
      return;
    }
    const payload = (await response.json()) as { id: string; name: string };
    setPlugins((current) => {
      if (editing) {
        return current.map((item) =>
          item.id === pluginEditingId
            ? {
                ...item,
                name: payload.name,
                version: pluginForm.version,
                plugin_type: pluginForm.plugin_type,
                endpoint: pluginForm.endpoint,
                actions,
                auth_type: pluginForm.auth_type,
                auth_ref: pluginForm.auth_ref || null,
                auth_config: authConfig
              }
            : item
        );
      }
      return [
        ...current,
        {
          id: payload.id,
          name: payload.name,
          version: pluginForm.version,
          plugin_type: pluginForm.plugin_type,
          endpoint: pluginForm.endpoint,
          actions,
          auth_type: pluginForm.auth_type,
          auth_ref: pluginForm.auth_ref || null,
          auth_config: authConfig
        }
      ];
    });
    resetPluginForm();
    showStatus(editing ? "Plugin updated." : "Plugin registered.");
  };

  const handleRegisterWorkflow = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    let inputSchema: WorkflowInputSchema | null = null;
    if (workflowForm.input_schema.trim()) {
      try {
        inputSchema = JSON.parse(workflowForm.input_schema) as WorkflowInputSchema;
      } catch {
        showStatus("Input schema must be valid JSON.");
        return;
      }
    }
    const response = await apiFetch(`${apiBase}/v1/workflows`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: workflowForm.name,
        description: workflowForm.description,
        plugin_id: workflowForm.pluginId,
        action: workflowForm.action,
        input_schema: inputSchema
      })
    });
    if (!response.ok) {
      showStatus("Failed to register workflow.");
      return;
    }
    const created = (await response.json()) as { id: string; name: string };
    setWorkflows((current) => [
      ...current,
      {
        id: created.id,
        name: created.name,
        description: workflowForm.description,
        plugin_id: workflowForm.pluginId,
        action: workflowForm.action,
        input_schema: inputSchema
      }
    ]);
    setWorkflowForm({ name: "", description: "", pluginId: "", action: "", input_schema: "" });
    showStatus("Workflow registered.");
  };

  const handleDeletePlugin = async (plugin: Plugin) => {
    const response = await apiFetch(`${apiBase}/v1/plugins/${plugin.id}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      showStatus("Failed to delete plugin.");
      return;
    }
    setPlugins((current) => current.filter((item) => item.id !== plugin.id));
    showStatus("Plugin deleted.");
  };

  const handleEditPlugin = (plugin: Plugin) => {
    setPluginEditingId(plugin.id);
    setPluginForm({
      name: plugin.name,
      endpoint: plugin.endpoint,
      version: plugin.version,
      plugin_type: plugin.plugin_type ?? "workflow",
      auth_type: plugin.auth_type ?? "none",
      auth_ref: plugin.auth_ref ?? "",
      auth_config: JSON.stringify(plugin.auth_config ?? {}, null, 2),
      actions: JSON.stringify(plugin.actions ?? {}, null, 2)
    });
    setActiveView("plugins");
  };

  const handleRunWorkflow = async (workflow: Workflow) => {
    let params: Record<string, unknown> = {};
    const rawParams = runParamsByWorkflow[workflow.id] ?? "{}";
    try {
      params = rawParams ? (JSON.parse(rawParams) as Record<string, unknown>) : {};
    } catch {
      showStatus("Run params must be valid JSON.");
      return;
    }
    const validationError = validateWorkflowParams(workflow, params);
    if (validationError) {
      showStatus(validationError);
      return;
    }
    const environment = runEnvByWorkflow[workflow.id] ?? "dev";
    const paramKeys = Object.keys(params).sort();
    const response = await apiFetch(`${apiBase}/v1/workflows/${workflow.id}/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ params, environment })
    });
    if (!response.ok) {
      const detail = await parseErrorDetail(response);
      setWorkflowRunNotice({
        outcome: "failed",
        workflowName: workflow.name,
        environment,
        paramKeys,
        error: detail ?? "Run request denied or failed."
      });
      showStatus(detail ?? "Run request denied or failed.");
      return;
    }
    const result = (await response.json()) as {
      run_id: string;
      job_id?: string;
      status?: string;
      approval_id?: string;
    };
    if (result.approval_id) {
      setWorkflowRunNotice({
        outcome: "pending",
        workflowName: workflow.name,
        environment,
        paramKeys,
        runId: result.run_id,
        jobId: result.job_id,
        approvalId: result.approval_id,
        approvalStatus: "pending",
        status: result.status ?? "pending approval"
      });
      showStatus(`Run ${result.run_id} pending approval (${result.approval_id}).`);
      return;
    }
    setWorkflowRunNotice({
      outcome: "submitted",
      workflowName: workflow.name,
      environment,
      paramKeys,
      runId: result.run_id,
      jobId: result.job_id,
      status: result.status ?? "submitted"
    });
    showStatus(`Run ${result.run_id} submitted (${result.status ?? "submitted"}).`);
  };

  const handleDeleteWorkflow = async (workflow: Workflow) => {
    const response = await apiFetch(`${apiBase}/v1/workflows/${workflow.id}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      showStatus("Workflow delete failed.");
      return;
    }
    setWorkflows((current) => current.filter((item) => item.id !== workflow.id));
    showStatus("Workflow deleted.");
  };

  const handleApprovalDecision = async (approvalId: string, decision: "approve" | "reject") => {
    const response = await apiFetch(`${apiBase}/v1/approvals/${approvalId}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision })
    });
    if (!response.ok) {
      showStatus("Approval decision failed.");
      return;
    }
    setApprovals((current) => current.filter((approval) => approval.id !== approvalId));
    showStatus(`Approval ${decision}d.`);
  };

  const handleRuntimeRunDecision = async (runId: string, decision: "approve" | "reject") => {
    const response = await apiFetch(`${apiBase}/v1/runs/${runId}/${decision}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: "UI decision" })
    });
    if (!response.ok) {
      const detail = await parseErrorDetail(response);
      showStatus(detail ? `Run decision failed: ${detail}` : "Run decision failed.");
      return;
    }
    showStatus(`Run ${decision}d.`);
  };

  const handleCreateAgentRun = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!agentRunForm.goal.trim()) {
      showStatus("Agent goal is required.");
      return;
    }
    const tools = agentRunForm.tools
      .split(/[,\n]/)
      .map((item) => item.trim())
      .filter(Boolean);
    const documents = agentRunForm.documents
      .split(/\n/)
      .map((item) => item.trim())
      .filter(Boolean);
    const response = await apiFetch(`${apiBase}/v1/agent/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        goal: agentRunForm.goal,
        environment: agentRunForm.environment,
        tools,
        documents
      })
    });
    if (!response.ok) {
      showStatus("Agent run denied or failed.");
      return;
    }
    const result = (await response.json()) as {
      run_id: string;
      status: string;
      approval_id?: string;
      evaluation?: { verdict: string };
    };
    if (result.approval_id) {
      showStatus(`Agent run ${result.run_id} pending approval (${result.approval_id}).`);
    } else {
      showStatus(
        `Agent run ${result.run_id} submitted (${result.status ?? result.evaluation?.verdict}).`
      );
    }
    const agentRunsResponse = await apiFetch(`${apiBase}/v1/agent/runs`);
    if (agentRunsResponse.ok) {
      const data = (await agentRunsResponse.json()) as AgentRun[];
      setAgentRuns(data);
    }
  };

  const handleMemorySearch = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!memorySearch.query.trim()) {
      showStatus("Memory query is required.");
      return;
    }
    const filters: Record<string, string> = {};
    if (memorySearch.type) filters.type = memorySearch.type;
    if (memorySearch.source) filters.source = memorySearch.source;
    if (memorySearch.agentType) filters.agent_type = memorySearch.agentType;
    const response = await apiFetch(`${apiBase}/v1/memory/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: memorySearch.query,
        top_k: Number(memorySearch.topK || 5),
        filters
      })
    });
    if (!response.ok) {
      showStatus("Memory search failed.");
      return;
    }
    const data = (await response.json()) as { results: MemoryResult[] };
    setMemoryResults(data.results ?? []);
  };

  const loadChatHistory = async (sessionId: string) => {
    const response = await apiFetch(`${apiBase}/v1/chat/sessions/${sessionId}/messages`);
    if (!response.ok) {
      showStatus("Failed to load chat history.");
      return;
    }
    const data = (await response.json()) as ChatMessage[];
    setChatMessages(data);
  };

  const handleSendChat = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!chatInput.trim()) {
      showStatus("Message is required.");
      return;
    }
    setChatBusy(true);
    const requestBody: { message: string; session_id?: string } = { message: chatInput };
    if (chatSessionId) {
      requestBody.session_id = chatSessionId;
    }
    const response = await apiFetch(`${apiBase}/v1/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody)
    });
    setChatBusy(false);
    if (!response.ok) {
      let detail = "";
      try {
        const data = (await response.json()) as { detail?: string };
        detail = data.detail ? ` (${data.detail})` : "";
      } catch {
        detail = "";
      }
      showStatus(`Chat request failed${detail}.`);
      return;
    }
    const payload = (await response.json()) as {
      session_id: string;
      response: string;
      tool_calls: Array<{ action: string }>;
      tool_results: Array<{ action: string; status: string }>;
    };
    if (!chatSessionId) {
      setChatSessionId(payload.session_id);
      await loadChatHistory(payload.session_id);
    } else {
      await loadChatHistory(chatSessionId);
    }
    setChatInput("");
  };

  const handleAssignIamRole = async (userId: string) => {
    const role = iamRoleSelections[userId];
    if (!role) {
      showStatus("Select a role to assign.");
      return;
    }
    const response = await apiFetch(`${apiBase}/v1/iam/users/${userId}/roles`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ roles: [role] })
    });
    if (!response.ok) {
      showStatus("Failed to assign role.");
      return;
    }
    showStatus("Role assigned.");
  };

  const grafanaUrl =
    (import.meta.env.VITE_GRAFANA_URL as string | undefined)?.trim() || "http://localhost:3001";
  const keycloakAdminUrl =
    (import.meta.env.VITE_KEYCLOAK_ADMIN_URL as string | undefined)?.trim() ||
    "http://localhost:8080/admin";
  const supportUrl = (import.meta.env.VITE_SUPPORT_URL as string | undefined)?.trim() || "";

  const navItems = [
    { id: "home", label: "Home", section: "core" },
    { id: "chat", label: "Chat", section: "core" },
    { id: "workflows", label: "Workflows", section: "core" },
    { id: "agents", label: "Agents", section: "core" },
    { id: "plugins", label: "Plugins", section: "core" },
    { id: "events", label: "Events", section: "core" },
    { id: "audits", label: "Audits", section: "core" },
    { id: "memory", label: "Memory", section: "core" },
    { id: "dashboard", label: "Dashboard", section: "ops" },
    { id: "settings", label: "Settings", section: "admin" },
    { id: "iam", label: "IAM", section: "admin" },
    { id: "help", label: "Help", section: "admin" }
  ];
  const navSections = [
    { id: "core", label: "Core" },
    { id: "ops", label: "Ops" },
    { id: "admin", label: "Admin" }
  ];
  const viewPermissions: Record<string, string[]> = {
    home: ["auth:me"],
    chat: ["chat:run"],
    workflows: ["workflow:read", "agent:run"],
    agents: ["agent:run", "agent:config:read"],
    plugins: ["plugin:read"],
    events: ["audit:read"],
    audits: ["audit:read"],
    dashboard: ["audit:read"],
    memory: ["memory:read"],
    settings: ["agent:config:read"],
    iam: ["iam:read"],
    help: ["auth:me"]
  };
  const navVisible = navItems.filter((item) => {
    const required = viewPermissions[item.id] ?? [];
    if (required.length === 0) return true;
    return required.some((permission) => hasPermission(permission));
  });
  const navIcons: Record<string, JSX.Element> = {
    home: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M3 11.5 12 4l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
      </svg>
    ),
    chat: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M6 6h12a3 3 0 0 1 3 3v5a3 3 0 0 1-3 3H9l-4 3v-3H6a3 3 0 0 1-3-3V9a3 3 0 0 1 3-3z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
      </svg>
    ),
    workflows: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="6" cy="6" r="3" fill="none" stroke="currentColor" strokeWidth="1.6" />
        <circle cx="18" cy="6" r="3" fill="none" stroke="currentColor" strokeWidth="1.6" />
        <circle cx="12" cy="18" r="3" fill="none" stroke="currentColor" strokeWidth="1.6" />
        <path
          d="M8.5 7.5 10.5 15M15.5 7.5 13.5 15"
          stroke="currentColor"
          strokeWidth="1.6"
          fill="none"
        />
      </svg>
    ),
    agents: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="5" y="7" width="14" height="11" rx="3" fill="none" stroke="currentColor" strokeWidth="1.6" />
        <circle cx="10" cy="12.5" r="1.3" fill="currentColor" />
        <circle cx="14" cy="12.5" r="1.3" fill="currentColor" />
        <path d="M9 4h6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    ),
    plugins: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M8 7h4a4 4 0 0 1 0 8H8m8-8v-3m0 3v4"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
        />
      </svg>
    ),
    events: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M12 4a6 6 0 0 1 6 6v4l2 2H4l2-2v-4a6 6 0 0 1 6-6z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
        <path d="M9.5 20a2.5 2.5 0 0 0 5 0" stroke="currentColor" strokeWidth="1.6" fill="none" />
      </svg>
    ),
    audits: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M7 4h7l5 5v11a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
        />
        <path d="M14 4v5h5" stroke="currentColor" strokeWidth="1.6" fill="none" />
      </svg>
    ),
    memory: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <ellipse cx="12" cy="6" rx="7" ry="3" fill="none" stroke="currentColor" strokeWidth="1.6" />
        <path d="M5 6v8c0 1.7 3.1 3 7 3s7-1.3 7-3V6" fill="none" stroke="currentColor" strokeWidth="1.6" />
      </svg>
    ),
    dashboard: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 19h16" stroke="currentColor" strokeWidth="1.6" />
        <path d="M7 16V9m5 7V6m5 10v-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    ),
    settings: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8zm7 4 2 1-2 1a7.7 7.7 0 0 1-.8 2l1 2-2 1-1-2a7.7 7.7 0 0 1-2 0l-1 2-2-1 1-2a7.7 7.7 0 0 1-.8-2l-2-1 2-1a7.7 7.7 0 0 1 .8-2l-1-2 2-1 1 2a7.7 7.7 0 0 1 2 0l1-2 2 1-1 2a7.7 7.7 0 0 1 .8 2z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.3"
          strokeLinejoin="round"
        />
      </svg>
    ),
    iam: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 4 4 7v5c0 5 3.5 7.5 8 8 4.5-.5 8-3 8-8V7z" fill="none" stroke="currentColor" strokeWidth="1.6" />
      </svg>
    ),
    help: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.6" />
        <path d="M9.5 9a2.5 2.5 0 1 1 4.2 1.8c-.7.7-1.4 1.2-1.4 2.2" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        <circle cx="12" cy="17" r="1" fill="currentColor" />
      </svg>
    )
  };
  const viewDescriptions: Record<string, string> = {
    home: "Chat, approvals, and audit signals in one glance.",
    chat: "Full chat workspace with history and tool results.",
    workflows: "Register workflows, trigger runs, and review executions.",
    agents: "Agent status, configuration, and run history.",
    plugins: "Register and manage plugin endpoints.",
    events: "Review alerts and event coordinator actions.",
    audits: "Search audit logs across all services.",
    dashboard: "Grafana metrics and service health.",
    memory: "Search long-term memory and summaries.",
    settings: "Agent configs and system preferences.",
    iam: "User management and access control.",
    help: "Support requests and ticket history.",
    profile: "Account details, roles, and access controls."
  };
  const activeLabel =
    navItems.find((item) => item.id === activeView)?.label ??
    (activeView === "profile" ? "Profile" : "Home");
  const filteredWorkflows = workflowSearch
    ? workflows.filter((workflow) =>
        matchesSearch(
          `${workflow.name} ${workflow.description ?? ""} ${workflow.action}`,
          workflowSearch
        )
      )
    : workflows;
  const filteredPlugins = pluginSearch
    ? plugins.filter((plugin) =>
        matchesSearch(
          `${plugin.name} ${plugin.plugin_type ?? ""} ${plugin.endpoint}`,
          pluginSearch
        )
      )
    : plugins;
  const filteredEvents = eventSearch
    ? events.filter((event) =>
        matchesSearch(
          `${event.event_type} ${event.summary ?? ""} ${event.source ?? ""}`,
          eventSearch
        )
      )
    : events;
  const auditSummary = auditEvents.reduce(
    (acc, event) => {
      if (event.outcome === "deny") {
        acc.denied += 1;
      } else {
        acc.allowed += 1;
      }
      return acc;
    },
    { allowed: 0, denied: 0 }
  );

  if (!auth) {
    return (
      <div className="app-login">
        <div className="login-card">
          <div>
            <span className="app-kicker">Control Plane</span>
            <h1>{APP_NAME}</h1>
            <p>{APP_TAGLINE}</p>
          </div>
          <div className="auth-card">
            {loading ? (
              <span>Checking session…</span>
            ) : (
              <a className="primary" href={`${apiBase}/v1/auth/login`}>
                Log in with OIDC
              </a>
            )}
            <div className="muted">OIDC login is required to access the console.</div>
          </div>
        </div>
      </div>
    );
  }

  const recentChat = chatMessages.slice(-6);
  const recentApprovals = approvals.slice(0, 5);
  const recentAudits = auditEvents.slice(0, 8);
  const displayName = auth.username ?? auth.actor_id;
  const initials = displayName
    .split(/[\s@._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((chunk) => chunk[0].toUpperCase())
    .join("");
  const accountBase =
    iamStatus?.admin_url?.replace(/\/admin\/?$/, "") ||
    keycloakAdminUrl.replace(/\/admin\/?$/, "");
  const accountUrl =
    iamStatus?.realm && accountBase ? `${accountBase}/realms/${iamStatus.realm}/account` : null;
  const chatHealthStatus =
    chatHealth?.agent_runtime?.llm?.status ??
    chatHealth?.agent_runtime?.status ??
    chatHealth?.status ??
    "unknown";
  const chatHealthBadge = mapRunStatusBadge(chatHealthStatus);
  const chatCorrelationIds = new Set(
    chatSessionEvents
      .filter((event) => {
        const sessionMatch = chatSessionId ? extractEventSessionId(event) === chatSessionId : false;
        const actor = extractEventActorId(event);
        return sessionMatch && actor === auth.actor_id;
      })
      .map((event) => event.correlation_id?.trim() ?? "")
      .filter(Boolean)
  );
  const sessionActivityEvents = chatSessionEvents
    .filter((event) => {
      const actor = extractEventActorId(event);
      const correlationId = event.correlation_id?.trim() ?? "";
      const sessionMatch = chatSessionId ? extractEventSessionId(event) === chatSessionId : false;
      if (sessionMatch) {
        return actor === auth.actor_id;
      }
      if (correlationId && chatCorrelationIds.has(correlationId)) {
        return true;
      }
      return false;
    })
    .sort((a, b) => {
      const left = new Date(a.received_at).getTime();
      const right = new Date(b.received_at).getTime();
      if (left !== right) return left - right;
      return a.id.localeCompare(b.id);
    });
  const workflowNoticeMeta = workflowRunNotice
    ? (() => {
        const statusLabel =
          workflowRunNotice.status ??
          (workflowRunNotice.outcome === "failed"
            ? "failed"
            : workflowRunNotice.outcome === "pending"
              ? "pending approval"
              : "submitted");
        const title =
          workflowRunNotice.outcome === "failed"
            ? "Workflow submission failed"
            : workflowRunNotice.outcome === "pending"
              ? "Workflow pending approval"
              : isSuccessRunStatus(statusLabel)
                ? "Workflow completed"
                : "Workflow submitted";
        const statusClass = mapRunStatusBadge(statusLabel, workflowRunNotice.approvalStatus);
        const message =
          workflowRunNotice.outcome === "failed"
            ? "The workflow run was not accepted."
            : workflowRunNotice.outcome === "pending"
              ? "Approval is required before execution."
              : isSuccessRunStatus(statusLabel)
                ? "The workflow run completed successfully."
                : "The workflow run was accepted.";
        return { title, statusClass, statusText: statusLabel, message };
      })()
    : null;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="app-kicker">Control Plane</span>
          <h1>{APP_NAME}</h1>
          <p>{APP_TAGLINE}</p>
        </div>
        <div className="sidebar-user">
          <div>
            <strong>{displayName}</strong>
            <span className="muted"> · {auth.tenant_id}</span>
          </div>
          <div className="muted">Roles: {auth.roles.join(", ") || "none"}</div>
          <form action={`${apiBase}/v1/auth/logout`} method="post">
            <button className="secondary" type="submit">
              Log out
            </button>
          </form>
        </div>
        <nav className="sidebar-nav">
          {navSections.map((section) => {
            const items = navVisible.filter((item) => item.section === section.id);
            if (items.length === 0) {
              return null;
            }
            const collapsed = collapsedSections[section.id] ?? false;
            return (
              <div key={section.id} className="nav-section">
                <button
                  type="button"
                  className="nav-section-toggle"
                  onClick={() =>
                    setCollapsedSections((current) => ({
                      ...current,
                      [section.id]: !collapsed
                    }))
                  }
                >
                  <span>{section.label}</span>
                  <span>{collapsed ? "+" : "–"}</span>
                </button>
                {!collapsed ? (
                  <div className="nav-section-items">
                    {items.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        className={`nav-item ${activeView === item.id ? "active" : ""}`}
                        onClick={() => setActiveView(item.id)}
                      >
                        <span className="nav-icon">{navIcons[item.id]}</span>
                        {item.label}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })}
        </nav>
        <div className="sidebar-links">
          <a className="secondary" href={`${apiBase}/docs`}>
            API docs
          </a>
          <a className="secondary" href={grafanaUrl} target="_blank" rel="noreferrer">
            Grafana
          </a>
        </div>
      </aside>
      <main className="main">
        <header className="main-header">
          <div>
            <h2>{activeLabel}</h2>
            <p className="muted">{viewDescriptions[activeView]}</p>
          </div>
          <div className="main-header-actions">
            {statusMessage ? <span className="status-pill">{statusMessage}</span> : null}
            <button
              type="button"
              className="profile-button"
              onClick={() => setActiveView("profile")}
            >
              <span className="profile-avatar">{initials || "U"}</span>
              <span>{displayName}</span>
            </button>
          </div>
        </header>
        <div className="main-content">
          {activeView === "home" && (
            <section className="view-grid">
              <div className="view-row view-row--split">
                <div className="panel-card">
                  <div className="panel-header">
                    <h3>Chat</h3>
                    <button className="secondary" onClick={() => setActiveView("chat")}>
                      Open chat
                    </button>
                  </div>
                  {recentChat.length === 0 ? (
                    <p className="muted">No chat history yet.</p>
                  ) : (
                    <div className="run-list">
                      {recentChat.map((message) => (
                        <div key={message.id} className="run-row">
                          <div>
                            <strong>{message.role}</strong>
                            <div>{message.content}</div>
                          </div>
                          <div className="muted">
                            {new Date(message.created_at).toLocaleTimeString()}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <div className="panel-card">
                  <div className="panel-header">
                    <h3>Approvals</h3>
                    <span className="muted">{approvals.length} pending</span>
                  </div>
                  {recentApprovals.length === 0 ? (
                    <p className="muted">No approvals pending.</p>
                  ) : (
                    <div className="approval-list">
                      {recentApprovals.map((approval) => (
                        <div key={approval.id} className="approval-row">
                          <div>
                            <strong>{approval.target_name}</strong>
                            <div className="muted">
                              {approval.target_type} · requested by{" "}
                              {approval.requested_by_name ?? approval.requested_by}
                            </div>
                            <div className="muted">{approval.plan_summary ?? "No summary."}</div>
                          </div>
                          <div className="approval-actions">
                            <button
                              className="secondary"
                              onClick={() => handleApprovalDecision(approval.id, "reject")}
                            >
                              Reject
                            </button>
                            <button
                              className="primary"
                              onClick={() => handleApprovalDecision(approval.id, "approve")}
                            >
                              Approve
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              <div className="panel-card panel-card--wide">
                <div className="panel-header">
                  <h3>Audit stream</h3>
                  <button className="secondary" onClick={() => setActiveView("audits")}>
                    View all
                  </button>
                </div>
                {recentAudits.length === 0 ? (
                  <p className="muted">No audit events yet.</p>
                ) : (
                  <div className="audit-list">
                    {recentAudits.map((event) => (
                      <div key={event.id} className="audit-row">
                        <div>
                          <strong>{event.event_type}</strong>
                          <div className="muted">
                            <span
                              className={`status-badge status-badge--${normalizeStatusClass(
                                event.outcome
                              )}`}
                            >
                              {event.outcome}
                            </span>
                            {` · ${event.source}`}
                          </div>
                          {typeof event.details.description === "string" &&
                          event.details.description ? (
                            <div className="muted">{event.details.description}</div>
                          ) : null}
                        </div>
                        <div className="muted">
                          {new Date(event.created_at).toLocaleString()}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </section>
          )}

          {activeView === "chat" && (
            <section className="view-grid">
              <div className="chat-layout">
                <div className="chat-main-column">
                  <div className="panel-card chat-sessions-card">
                    <div className="panel-header">
                      <h3>Sessions</h3>
                      <button
                        className="secondary"
                        onClick={() => {
                          setChatSessionId(null);
                          setChatMessages([]);
                          setChatSessionEvents([]);
                        }}
                      >
                        New chat
                      </button>
                    </div>
                    {chatSessions.length === 0 ? (
                      <p className="muted">No chat sessions yet.</p>
                    ) : (
                      <div className="run-list">
                        {chatSessions.map((session) => (
                          <button
                            type="button"
                            key={session.id}
                            className={`secondary ${chatSessionId === session.id ? "active" : ""}`}
                            onClick={async () => {
                              setChatSessionId(session.id);
                              await loadChatHistory(session.id);
                            }}
                          >
                            {session.title}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="panel-card chat-conversation-card">
                    <div className="panel-header">
                      <h3>Conversation</h3>
                      <span className={`status-badge ${chatHealthBadge}`}>
                        LLM {chatHealthStatus}
                      </span>
                    </div>
                    <div className="chat-thread" ref={chatThreadRef}>
                      {chatMessages.length === 0 ? (
                        <p className="muted">Start a conversation to see history.</p>
                      ) : (
                        chatMessages.map((message) => (
                          <div
                            key={message.id}
                            className={`chat-message chat-message--${message.role}`}
                          >
                            <div className="chat-meta">
                              <span className="chat-role">{message.role}</span>
                              <span className="muted">
                                {new Date(message.created_at).toLocaleString()}
                              </span>
                            </div>
                            <div className="chat-bubble">{renderChatContent(message.content)}</div>
                            {(() => {
                              const toolItems = normalizeChatToolItems(message.tool_results);
                              return toolItems.length ? (
                                <div className="tool-summary">
                                  {toolItems
                                    .flatMap((item) => renderChatToolSummary(item))
                                    .filter((value) => Boolean(value))
                                    .map((value, index) => (
                                      <div key={`${message.id}-tool-${index}`}>{value}</div>
                                    ))}
                                </div>
                              ) : null;
                            })()}
                          </div>
                        ))
                      )}
                    </div>
                    <form className="stack-form" onSubmit={handleSendChat}>
                      <label>
                        Message
                        <textarea
                          rows={3}
                          value={chatInput}
                          onChange={(event) => setChatInput(event.target.value)}
                          placeholder="List workflows, run a job, or show audits..."
                        />
                      </label>
                      <button className="primary" type="submit" disabled={chatBusy}>
                        {chatBusy ? "Sending..." : "Send"}
                      </button>
                    </form>
                  </div>
                </div>
                <div className="panel-card chat-activity-column">
                  <div className="panel-header">
                    <h3>Session Activity</h3>
                    <span className="muted">
                      {chatSessionId ? `Session ${chatSessionId.slice(0, 8)}` : "No session selected"}
                    </span>
                  </div>
                  {chatSessionEventsError ? <p className="muted">{chatSessionEventsError}</p> : null}
                  {!chatSessionId ? (
                    <p className="muted">Start or select a chat session to view activity.</p>
                  ) : sessionActivityEvents.length === 0 ? (
                    <p className="muted">No events for this chat session yet.</p>
                  ) : (
                    <div className="session-activity-list">
                      {sessionActivityEvents.map((event) => {
                        const statusLabel = normalizeEventStatus(event.status);
                        const errorDetail = extractEventError(event);
                        const metadata = {
                          source: event.source,
                          environment: event.environment,
                          event_id: event.id,
                          actor_id: extractEventActorId(event) || null,
                          session_id: extractEventSessionId(event) || null,
                          correlation_id: event.correlation_id ?? null,
                          received_at: event.received_at
                        };
                        return (
                          <details key={event.id} className="session-activity-event">
                            <summary>
                              <div className="session-activity-header">
                                <strong>{event.summary || event.event_type}</strong>
                                <span
                                  className={`status-badge status-badge--${normalizeStatusClass(
                                    statusLabel
                                  )}`}
                                >
                                  {statusLabel}
                                </span>
                              </div>
                              <div className="session-activity-meta muted">
                                <span>Event Type: {mapEventTypeLabel(event.event_type)}</span>
                                <span>{new Date(event.received_at).toLocaleString()}</span>
                                <span>
                                  Correlation ID: {event.correlation_id || "unknown"}
                                </span>
                              </div>
                            </summary>
                            <div className="session-activity-details">
                              <pre className="modal-pre">
                                {JSON.stringify({ metadata, payload: event.details }, null, 2)}
                              </pre>
                              {errorDetail ? (
                                <div className="notice-card">Error details: {errorDetail}</div>
                              ) : null}
                            </div>
                          </details>
                        );
                      })}
                      <div ref={sessionActivityEndRef} />
                    </div>
                  )}
                </div>
              </div>
            </section>
          )}

          {activeView === "workflows" && (
            <section className="view-grid">
              <div className="panel-grid">
                <form className="panel-card" onSubmit={handleRegisterWorkflow}>
                  <h3>Register workflow</h3>
                  <label>
                    Name
                    <input
                      value={workflowForm.name}
                      onChange={(event) =>
                        setWorkflowForm({ ...workflowForm, name: event.target.value })
                      }
                      placeholder="Daily data refresh"
                      required
                    />
                  </label>
                  <label>
                    Description
                    <input
                      value={workflowForm.description}
                      onChange={(event) =>
                        setWorkflowForm({ ...workflowForm, description: event.target.value })
                      }
                    />
                  </label>
                  <label>
                    Plugin
                    <select
                      value={workflowForm.pluginId}
                      onChange={(event) =>
                        setWorkflowForm({ ...workflowForm, pluginId: event.target.value })
                      }
                      required
                    >
                      <option value="">Select plugin</option>
                      {plugins.map((plugin) => (
                        <option key={plugin.id} value={plugin.id}>
                          {plugin.name} ({plugin.version})
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Action
                    <input
                      value={workflowForm.action}
                      onChange={(event) =>
                        setWorkflowForm({ ...workflowForm, action: event.target.value })
                      }
                      placeholder="trigger_dag"
                      required
                    />
                  </label>
                  <label>
                    Input schema (JSON)
                    <textarea
                      rows={3}
                      value={workflowForm.input_schema}
                      onChange={(event) =>
                        setWorkflowForm({ ...workflowForm, input_schema: event.target.value })
                      }
                      placeholder='{"type":"object","required":["server_name"]}'
                    />
                  </label>
                  <button className="primary" type="submit">
                    Add workflow
                  </button>
                </form>
                <div className="panel-card panel-card--wide">
                  <div className="panel-header">
                    <h3>Existing workflows</h3>
                    <input
                      className="inline-input"
                      placeholder="Search workflows"
                      value={workflowSearch}
                      onChange={(event) => setWorkflowSearch(event.target.value)}
                    />
                  </div>
                  {filteredWorkflows.length === 0 ? (
                    <p className="muted">No workflows matched your search.</p>
                  ) : (
                    <div className="workflow-list">
                      {filteredWorkflows.map((workflow) => (
                        <div key={workflow.id} className="workflow-row">
                          <div>
                            <strong>{workflow.name}</strong>
                            <div className="muted">
                              {workflow.description || "No description"} · {workflow.action}
                            </div>
                            {getRequiredFields(workflow.input_schema).length > 0 && (
                              <div className="muted">
                                Required: {getRequiredFields(workflow.input_schema).join(", ")}
                              </div>
                            )}
                          </div>
                          <div className="workflow-actions">
                            <select
                              value={runEnvByWorkflow[workflow.id] ?? "dev"}
                              onChange={(event) =>
                                setRunEnvByWorkflow((current) => ({
                                  ...current,
                                  [workflow.id]: event.target.value
                                }))
                              }
                            >
                              <option value="dev">dev</option>
                              <option value="stage">stage</option>
                              <option value="prod">prod</option>
                            </select>
                            <textarea
                              rows={2}
                              placeholder='{"dag_id":"infra-refresh"}'
                              value={runParamsByWorkflow[workflow.id] ?? "{}"}
                              onChange={(event) =>
                                setRunParamsByWorkflow((current) => ({
                                  ...current,
                                  [workflow.id]: event.target.value
                                }))
                              }
                            />
                            <div className="workflow-action-row">
                              <button
                                className="secondary"
                                onClick={() => handleRunWorkflow(workflow)}
                              >
                                Run
                              </button>
                              <button
                                className="secondary"
                                onClick={() => handleDeleteWorkflow(workflow)}
                              >
                                Delete
                              </button>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <div className="panel-card panel-card--wide">
                  <h3>Recent workflow runs</h3>
                  {runs.length === 0 ? (
                    <p className="muted">No runs yet.</p>
                  ) : (
                    <div className="run-list">
                      {runs.map((run) => (
                        <div
                          key={run.id}
                          id={`run-row-${run.id}`}
                          className="run-row run-row--clickable"
                          role="button"
                          tabIndex={0}
                          onClick={() => {
                            setSelectedAgentRun(null);
                            setSelectedRun(run);
                          }}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              setSelectedAgentRun(null);
                              setSelectedRun(run);
                            }
                          }}
                          aria-label={`View details for ${run.workflow_name}`}
                        >
                          <div>
                            <strong>{run.workflow_name}</strong>
                            <div className="muted">
                              <span
                                className={`status-badge status-badge--${normalizeStatusClass(
                                  run.status
                                )}`}
                              >
                                {run.status}
                              </span>
                              {` · ${run.environment}`}
                              {run.approval_status ? ` · approval ${run.approval_status}` : ""}
                              {run.job_id ? ` · ${run.job_id}` : ""}
                              {run.gitops?.status ? ` · gitops ${run.gitops.status}` : ""}
                            </div>
                          </div>
                          <div className="muted">{new Date(run.created_at).toLocaleString()}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <div className="panel-card panel-card--wide">
                  <h3>Agent runs</h3>
                  <p className="muted">Agent runs now live under the Agents tab.</p>
                </div>
              </div>
            </section>
          )}

          {activeView === "agents" && (
            <section className="view-grid">
              <div className="panel-grid">
                <div className="panel-card">
                  <h3>Status</h3>
                  <div className="summary-row">
                    <span className="status-badge status-badge--info">
                      total runs: {agentRuns.length}
                    </span>
                    {agentRuns[0] ? (
                      <span className="status-badge status-badge--neutral">
                        last: {agentRuns[0].status}
                      </span>
                    ) : null}
                  </div>
                  <p className="muted">
                    Status reflects the latest agent run and evaluation metadata.
                  </p>
                </div>
                <div className="panel-card panel-card--wide">
                  <h3>Create agent run</h3>
                  <form className="inline-form" onSubmit={handleCreateAgentRun}>
                    <input
                      placeholder="Goal (e.g. Refresh cache safely)"
                      value={agentRunForm.goal}
                      onChange={(event) =>
                        setAgentRunForm((current) => ({ ...current, goal: event.target.value }))
                      }
                      disabled={!canRunAgents}
                    />
                    <select
                      value={agentRunForm.environment}
                      onChange={(event) =>
                        setAgentRunForm((current) => ({
                          ...current,
                          environment: event.target.value
                        }))
                      }
                      disabled={!canRunAgents}
                    >
                      <option value="dev">dev</option>
                      <option value="stage">stage</option>
                      <option value="prod">prod</option>
                    </select>
                    <input
                      placeholder="Tools (comma or newline separated)"
                      value={agentRunForm.tools}
                      onChange={(event) =>
                        setAgentRunForm((current) => ({ ...current, tools: event.target.value }))
                      }
                      disabled={!canRunAgents}
                    />
                    <textarea
                      rows={2}
                      placeholder="Documents (one per line)"
                      value={agentRunForm.documents}
                      onChange={(event) =>
                        setAgentRunForm((current) => ({ ...current, documents: event.target.value }))
                      }
                      disabled={!canRunAgents}
                    />
                    <button className="primary" type="submit" disabled={!canRunAgents}>
                      Create agent run
                    </button>
                    {!canRunAgents ? (
                      <span className="muted">Need agent:run permission.</span>
                    ) : null}
                  </form>
                </div>
                <div className="panel-card panel-card--wide">
                  <h3>Agent history</h3>
                  {agentRuns.length === 0 ? (
                    <p className="muted">No agent runs yet.</p>
                  ) : (
                    <div className="run-list">
                      {agentRuns.map((run) => (
                        <div
                          key={run.id}
                          className="run-row run-row--clickable"
                          role="button"
                          tabIndex={0}
                          onClick={() => {
                            setSelectedRun(null);
                            setSelectedAgentRun(run);
                          }}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              setSelectedRun(null);
                              setSelectedAgentRun(run);
                            }
                          }}
                          aria-label={`View details for agent run ${run.goal}`}
                        >
                          <div>
                            <strong>{run.goal}</strong>
                            <div className="muted">
                              <span
                                className={`status-badge status-badge--${normalizeStatusClass(
                                  run.status
                                )}`}
                              >
                                {run.status}
                              </span>
                              {` · ${run.environment}`}
                              {run.evaluation
                                ? ` · score ${run.evaluation.score.toFixed(2)} (${run.evaluation.verdict})`
                                : ""}
                              {run.memory_used ? " · memory" : ""}
                              {run.runtime?.status ? ` · runtime ${run.runtime.status}` : ""}
                            </div>
                          </div>
                          <div className="muted">
                            {new Date(run.created_at).toLocaleString()}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <div className="panel-card panel-card--wide">
                  <h3>Agent configs</h3>
                  {agentConfigs.length === 0 ? (
                    <p className="muted">No agent configs available for this account.</p>
                  ) : (
                    <div className="config-list">
                      {agentConfigs.map((cfg) => {
                        const draft = agentConfigDrafts[cfg.agent_type] ?? cfg;
                        return (
                          <div key={cfg.agent_type} className="config-row">
                            <div className="config-meta">
                              <strong>{cfg.agent_type}</strong>
                              <span className="muted">{cfg.source}</span>
                            </div>
                            <label>
                              API URL
                              <input
                                value={draft.api_url}
                                onChange={(event) =>
                                  setAgentConfigDrafts((current) => ({
                                    ...current,
                                    [cfg.agent_type]: { ...draft, api_url: event.target.value }
                                  }))
                                }
                                readOnly={!canWriteAgentConfigs}
                              />
                            </label>
                            <label>
                              Model
                              <input
                                value={draft.model}
                                onChange={(event) =>
                                  setAgentConfigDrafts((current) => ({
                                    ...current,
                                    [cfg.agent_type]: { ...draft, model: event.target.value }
                                  }))
                                }
                                readOnly={!canWriteAgentConfigs}
                              />
                            </label>
                            <label>
                              API key ref
                              <input
                                value={draft.api_key_ref ?? ""}
                                onChange={(event) =>
                                  setAgentConfigDrafts((current) => ({
                                    ...current,
                                    [cfg.agent_type]: { ...draft, api_key_ref: event.target.value }
                                  }))
                                }
                                placeholder="env:LLM_API_KEY"
                                readOnly={!canWriteAgentConfigs}
                              />
                              <div className="muted">
                                Use <code>env:VAR</code> or{" "}
                                <code>secretkeyref:plugin:&lt;name&gt;:&lt;path&gt;</code>.
                              </div>
                            </label>
                            <button
                              className="secondary"
                              onClick={() => handleUpdateAgentConfig(cfg.agent_type)}
                              disabled={!canWriteAgentConfigs}
                            >
                              Save config
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            </section>
          )}

          {activeView === "plugins" && (
            <section className="view-grid">
              <div className="panel-grid">
                <form className="panel-card" onSubmit={handleRegisterPlugin}>
                  <div className="panel-header">
                    <h3>{pluginEditingId ? "Edit plugin" : "Register plugin"}</h3>
                    {pluginEditingId ? (
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => resetPluginForm()}
                      >
                        Cancel edit
                      </button>
                    ) : null}
                  </div>
                  <label>
                    Name
                    <input
                      value={pluginForm.name}
                      onChange={(event) =>
                        setPluginForm({ ...pluginForm, name: event.target.value })
                      }
                      placeholder="airflow"
                      required
                    />
                  </label>
                  <label>
                    Type
                    <select
                      value={pluginForm.plugin_type}
                      onChange={(event) =>
                        setPluginForm({ ...pluginForm, plugin_type: event.target.value })
                      }
                    >
                      <option value="workflow">Workflow</option>
                      <option value="secret">Secret</option>
                      <option value="mcp">MCP Server</option>
                      <option value="api">API Endpoint</option>
                      <option value="other">Other</option>
                    </select>
                  </label>
                  <label>
                    Endpoint
                    <input
                      value={pluginForm.endpoint}
                      onChange={(event) =>
                        setPluginForm({ ...pluginForm, endpoint: event.target.value })
                      }
                      placeholder="http://plugin-gateway:8002/invoke"
                      required
                    />
                  </label>
                  <label>
                    Version
                    <input
                      value={pluginForm.version}
                      onChange={(event) =>
                        setPluginForm({ ...pluginForm, version: event.target.value })
                      }
                    />
                  </label>
                  <label>
                    Auth type
                    <select
                      value={pluginForm.auth_type}
                      onChange={(event) =>
                        setPluginForm({ ...pluginForm, auth_type: event.target.value })
                      }
                    >
                      <option value="none">None</option>
                      <option value="basic">Basic</option>
                      <option value="bearer">Bearer</option>
                      <option value="api_key">API key</option>
                      <option value="oauth">OAuth</option>
                      <option value="mtls">mTLS</option>
                      <option value="secret_ref">Secret ref</option>
                    </select>
                  </label>
                  <label>
                    Auth reference
                    <input
                      value={pluginForm.auth_ref}
                      onChange={(event) =>
                        setPluginForm({ ...pluginForm, auth_ref: event.target.value })
                      }
                      placeholder="secretkeyref:plugin:vault-resolver:kv/autonoma#token"
                    />
                  </label>
                  <label>
                    Auth config (JSON)
                    <textarea
                      rows={3}
                      value={pluginForm.auth_config}
                      onChange={(event) =>
                        setPluginForm({ ...pluginForm, auth_config: event.target.value })
                      }
                    />
                  </label>
                  <label>
                    Actions (JSON)
                    <textarea
                      rows={4}
                      value={pluginForm.actions}
                      onChange={(event) => setPluginForm({ ...pluginForm, actions: event.target.value })}
                    />
                  </label>
                  <button className="primary" type="submit">
                    {pluginEditingId ? "Save changes" : "Add plugin"}
                  </button>
                </form>
                <div className="panel-card panel-card--wide">
                  <div className="panel-header">
                    <h3>Registered plugins</h3>
                    <input
                      className="inline-input"
                      placeholder="Search plugins"
                      value={pluginSearch}
                      onChange={(event) => setPluginSearch(event.target.value)}
                    />
                  </div>
                  {filteredPlugins.length === 0 ? (
                    <p className="muted">No plugins matched your search.</p>
                  ) : (
                    <div className="run-list">
                      {["workflow", "secret", "mcp", "api", "other"].map((category) => {
                        const categoryPlugins = filteredPlugins.filter(
                          (plugin) => (plugin.plugin_type || "workflow") === category
                        );
                        if (categoryPlugins.length === 0) {
                          return null;
                        }
                        return (
                          <div key={category} className="run-row run-row--stack">
                            <div className="muted">
                              {category.toUpperCase()} ({categoryPlugins.length})
                            </div>
                            {categoryPlugins.map((plugin) => (
                              <div key={plugin.id} className="run-row">
                                <div>
                                  <strong>{plugin.name}</strong>
                                  <div className="muted">{plugin.endpoint}</div>
                                  <div className="muted">
                                    {plugin.version} · auth {plugin.auth_type ?? "none"}
                                  </div>
                                </div>
                                <div className="run-actions">
                                  <span className="muted">
                                    {Object.keys(plugin.actions || {}).length} actions
                                  </span>
                                  <button
                                    className="secondary"
                                    onClick={() => handleEditPlugin(plugin)}
                                  >
                                    Edit
                                  </button>
                                  <button
                                    className="secondary"
                                    onClick={() => handleDeletePlugin(plugin)}
                                  >
                                    Delete
                                  </button>
                                </div>
                              </div>
                            ))}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            </section>
          )}

          {activeView === "events" && (
            <section className="view-grid">
              <div className="panel-card panel-card--wide">
                <div className="panel-header">
                  <h3>Event ingestion</h3>
                  <div className="panel-header-actions">
                    <input
                      className="inline-input"
                      placeholder="Search alerts"
                      value={eventSearch}
                      onChange={(event) => setEventSearch(event.target.value)}
                    />
                    <button
                      className="secondary"
                      onClick={() => {
                        setEventsLive((value) => !value);
                        setEventsStreamError(null);
                      }}
                    >
                      {eventsLive ? "Pause live" : "Resume live"}
                    </button>
                  </div>
                </div>
                {eventsStreamError ? (
                  <p className="muted">Stream status: {eventsStreamError}</p>
                ) : null}
                {filteredEvents.length === 0 ? (
                  <p className="muted">No events matched your search.</p>
                ) : (
                  <div className="run-list">
                    {filteredEvents.map((event) => (
                      <div key={event.id} className="run-row">
                        <div>
                          <strong>{event.event_type}</strong>
                          <div className="muted">
                            {event.status} · {event.severity} · {event.environment} · {event.source}
                          </div>
                          <div>{event.summary}</div>
                          {event.correlation_id ? (
                            <div className="muted">correlation: {event.correlation_id}</div>
                          ) : null}
                          {event.actions?.evaluation ? (
                            <div className="muted">
                              eval: {event.actions.evaluation.verdict} · score{" "}
                              {event.actions.evaluation.score.toFixed(2)}
                            </div>
                          ) : null}
                          {event.actions?.tool_calls?.length ? (
                            <div className="muted">
                              tools:{" "}
                              {event.actions.tool_calls
                                .map((tool) => `${tool.tool ?? "tool"}:${tool.action ?? "action"}`)
                                .join(", ")}
                            </div>
                          ) : null}
                          {event.actions?.trail?.length ? (
                            <div className="muted">
                              trail:{" "}
                              {event.actions.trail
                                .map((entry) => {
                                  const status = entry.status ? `:${entry.status}` : "";
                                  const actor = entry.actor ? `@${entry.actor}` : "";
                                  return `${entry.step}${status}${actor}`;
                                })
                                .join(" → ")}
                            </div>
                          ) : null}
                        </div>
                        <div className="muted">
                          {new Date(event.received_at).toLocaleString()}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </section>
          )}

          {activeView === "audits" && (
            <section className="view-grid">
              <div className="panel-card panel-card--wide">
                <div className="panel-header">
                  <h3>Audit events</h3>
                  <div className="summary-row">
                    <span className="status-badge status-badge--allow">
                      {auditSummary.allowed} allow
                    </span>
                    <span className="status-badge status-badge--deny">
                      {auditSummary.denied} deny
                    </span>
                  </div>
                </div>
                <div className="audit-filters">
                  <input
                    placeholder="Source"
                    value={auditFilterDraft.source}
                    onChange={(event) =>
                      setAuditFilterDraft((current) => ({ ...current, source: event.target.value }))
                    }
                  />
                  <input
                    placeholder="Event type"
                    value={auditFilterDraft.eventType}
                    onChange={(event) =>
                      setAuditFilterDraft((current) => ({
                        ...current,
                        eventType: event.target.value
                      }))
                    }
                  />
                  <input
                    placeholder="Actor id"
                    value={auditFilterDraft.actorId}
                    onChange={(event) =>
                      setAuditFilterDraft((current) => ({
                        ...current,
                        actorId: event.target.value
                      }))
                    }
                  />
                  <input
                    placeholder="Outcome"
                    value={auditFilterDraft.outcome}
                    onChange={(event) =>
                      setAuditFilterDraft((current) => ({
                        ...current,
                        outcome: event.target.value
                      }))
                    }
                  />
                  <input
                    placeholder="Since (ISO)"
                    value={auditFilterDraft.since}
                    onChange={(event) =>
                      setAuditFilterDraft((current) => ({
                        ...current,
                        since: event.target.value
                      }))
                    }
                  />
                  <input
                    placeholder="Until (ISO)"
                    value={auditFilterDraft.until}
                    onChange={(event) =>
                      setAuditFilterDraft((current) => ({
                        ...current,
                        until: event.target.value
                      }))
                    }
                  />
                  <button className="secondary" onClick={() => setAuditFilters(auditFilterDraft)}>
                    Apply filters
                  </button>
                  <button
                    className="secondary"
                    onClick={() => {
                      const cleared = {
                        source: "",
                        eventType: "",
                        actorId: "",
                        outcome: "",
                        since: "",
                        until: ""
                      };
                      setAuditFilterDraft(cleared);
                      setAuditFilters(cleared);
                    }}
                  >
                    Reset filters
                  </button>
                </div>
                {auditEvents.length === 0 ? (
                  <p className="muted">No audit events available.</p>
                ) : (
                  <div className="audit-list">
                    {auditEvents.map((event) => (
                      <div key={event.id} className="audit-row">
                        <div>
                          <strong>{event.event_type}</strong>
                          <div className="muted">
                            <span
                              className={`status-badge status-badge--${normalizeStatusClass(
                                event.outcome
                              )}`}
                            >
                              {event.outcome}
                            </span>
                            {` · ${event.source} · ${event.actor_id}`}
                          </div>
                          {typeof event.details.description === "string" &&
                          event.details.description ? (
                            <div className="muted">{event.details.description}</div>
                          ) : null}
                        </div>
                        <div className="muted">
                          {new Date(event.created_at).toLocaleString()}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </section>
          )}

          {activeView === "dashboard" && (
            <section className="view-grid">
              <div className="panel-card panel-card--wide">
                <div className="panel-header">
                  <h3>Grafana dashboards</h3>
                  <a className="secondary" href={grafanaUrl} target="_blank" rel="noreferrer">
                    Open Grafana
                  </a>
                </div>
                <div className="dashboard-frame">
                  <iframe title="Grafana" src={grafanaUrl} />
                </div>
              </div>
            </section>
          )}

          {activeView === "memory" && (
            <section className="view-grid">
              <div className="panel-card panel-card--wide">
                <h3>Memory search</h3>
                <form className="inline-form" onSubmit={handleMemorySearch}>
                  <input
                    placeholder="Search query"
                    value={memorySearch.query}
                    onChange={(event) =>
                      setMemorySearch((current) => ({ ...current, query: event.target.value }))
                    }
                    disabled={!canReadMemory}
                  />
                  <div className="workflow-action-row">
                    <input
                      placeholder="Type (e.g. plan)"
                      value={memorySearch.type}
                      onChange={(event) =>
                        setMemorySearch((current) => ({ ...current, type: event.target.value }))
                      }
                      disabled={!canReadMemory}
                    />
                    <input
                      placeholder="Source (e.g. agent-runtime)"
                      value={memorySearch.source}
                      onChange={(event) =>
                        setMemorySearch((current) => ({ ...current, source: event.target.value }))
                      }
                      disabled={!canReadMemory}
                    />
                    <input
                      placeholder="Agent type"
                      value={memorySearch.agentType}
                      onChange={(event) =>
                        setMemorySearch((current) => ({ ...current, agentType: event.target.value }))
                      }
                      disabled={!canReadMemory}
                    />
                    <input
                      placeholder="Top K"
                      value={memorySearch.topK}
                      onChange={(event) =>
                        setMemorySearch((current) => ({ ...current, topK: event.target.value }))
                      }
                      disabled={!canReadMemory}
                    />
                  </div>
                  <div className="workflow-action-row">
                    <button className="secondary" type="submit" disabled={!canReadMemory}>
                      Search memory
                    </button>
                    <button
                      className="secondary"
                      type="button"
                      onClick={() =>
                        setMemorySearch({
                          query: "",
                          topK: "5",
                          type: "",
                          source: "",
                          agentType: ""
                        })
                      }
                      disabled={!canReadMemory}
                    >
                      Reset
                    </button>
                    {!canReadMemory ? (
                      <span className="muted">Need memory:read permission.</span>
                    ) : null}
                  </div>
                </form>
                {memoryResults.length === 0 ? (
                  <p className="muted">No memory results yet.</p>
                ) : (
                  <div className="run-list">
                    {memoryResults.map((item) => (
                      <div key={item.id} className="run-row">
                        <div>
                          <div className="memory-tags">
                            <span className="status-badge status-badge--info">
                              {String(item.metadata?.type ?? "record")}
                            </span>
                            {item.metadata?.source ? (
                              <span className="status-badge status-badge--neutral">
                                {String(item.metadata.source)}
                              </span>
                            ) : null}
                          </div>
                          <div className="muted">score {item.score.toFixed(3)}</div>
                          <div>{item.text}</div>
                        </div>
                        <div className="muted">{item.id.slice(0, 8)}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </section>
          )}

          {activeView === "settings" && (
            <section className="view-grid">
              <div className="panel-card panel-card--wide">
                <h3>LLM agent configs</h3>
                {agentConfigs.length === 0 ? (
                  <p className="muted">No agent configs available for this account.</p>
                ) : (
                  <div className="config-list">
                    {agentConfigs.map((cfg) => {
                      const draft = agentConfigDrafts[cfg.agent_type] ?? cfg;
                      return (
                        <div key={cfg.agent_type} className="config-row">
                          <div className="config-meta">
                            <strong>{cfg.agent_type}</strong>
                            <span className="muted">{cfg.source}</span>
                          </div>
                          <label>
                            API URL
                            <input
                              value={draft.api_url}
                              onChange={(event) =>
                                setAgentConfigDrafts((current) => ({
                                  ...current,
                                  [cfg.agent_type]: { ...draft, api_url: event.target.value }
                                }))
                              }
                              readOnly={!canWriteAgentConfigs}
                            />
                          </label>
                          <label>
                            Model
                            <input
                              value={draft.model}
                              onChange={(event) =>
                                setAgentConfigDrafts((current) => ({
                                  ...current,
                                  [cfg.agent_type]: { ...draft, model: event.target.value }
                                }))
                              }
                              readOnly={!canWriteAgentConfigs}
                            />
                          </label>
                          <label>
                            API key ref
                            <input
                              value={draft.api_key_ref ?? ""}
                              onChange={(event) =>
                                setAgentConfigDrafts((current) => ({
                                  ...current,
                                  [cfg.agent_type]: { ...draft, api_key_ref: event.target.value }
                                }))
                              }
                              placeholder="env:LLM_API_KEY"
                              readOnly={!canWriteAgentConfigs}
                            />
                            <div className="muted">
                              Use <code>env:VAR</code> or{" "}
                              <code>secretkeyref:plugin:&lt;name&gt;:&lt;path&gt;</code>.
                            </div>
                          </label>
                          <button
                            className="secondary"
                            onClick={() => handleUpdateAgentConfig(cfg.agent_type)}
                            disabled={!canWriteAgentConfigs}
                          >
                            Save config
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </section>
          )}

          {activeView === "iam" && (
            <section className="view-grid">
              <div className="panel-card panel-card--wide">
                <h3>IAM management</h3>
                {iamStatus && !iamStatus.configured ? (
                  <div className="notice-card">
                    <strong>IAM provider not configured.</strong>
                    <p className="muted">
                      Configure IAM integration to manage users from Autonoma. See
                      `IAM_PROVIDER`, `IAM_ADMIN_URL`, and `IAM_CLIENT_ID` in `.env`.
                    </p>
                  </div>
                ) : null}
                <div className="panel-header">
                  <div className="summary-row">
                    <span className="status-badge status-badge--info">
                      Provider: {iamStatus?.provider ?? "unknown"}
                    </span>
                    {iamStatus?.realm ? (
                      <span className="status-badge status-badge--neutral">
                        Realm: {iamStatus.realm}
                      </span>
                    ) : null}
                  </div>
                  <a className="secondary" href={keycloakAdminUrl} target="_blank" rel="noreferrer">
                    Open Keycloak admin
                  </a>
                </div>
                {iamUsers.length === 0 ? (
                  <p className="muted">No IAM users available.</p>
                ) : (
                  <div className="iam-grid">
                    {iamUsers.map((user) => (
                      <div key={user.id} className="run-row">
                        <div>
                          <strong>{user.username ?? user.email ?? user.id}</strong>
                          <div className="muted">
                            {user.email ?? "no email"} ·{" "}
                            {user.enabled ? "enabled" : "disabled"}
                          </div>
                        </div>
                        <div className="iam-actions">
                          <select
                            value={iamRoleSelections[user.id] ?? ""}
                            onChange={(event) =>
                              setIamRoleSelections((current) => ({
                                ...current,
                                [user.id]: event.target.value
                              }))
                            }
                          >
                            <option value="">Assign role</option>
                            {iamRoles.map((role) => (
                              <option key={role.id ?? role.name} value={role.name ?? ""}>
                                {role.name}
                              </option>
                            ))}
                          </select>
                          <button
                            className="secondary"
                            onClick={() => handleAssignIamRole(user.id)}
                          >
                            Assign
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </section>
          )}

          {activeView === "profile" && (
            <section className="view-grid">
              <div className="panel-card panel-card--wide">
                <div className="panel-header">
                  <h3>Profile</h3>
                  <form action={`${apiBase}/v1/auth/logout`} method="post">
                    <button className="secondary" type="submit">
                      Log out
                    </button>
                  </form>
                </div>
                <div className="profile-grid">
                  <div className="profile-card">
                    <h4>Identity</h4>
                    <p>
                      <strong>{displayName}</strong>
                    </p>
                    <p className="muted">Actor ID: {auth.actor_id}</p>
                    <p className="muted">Tenant: {auth.tenant_id}</p>
                  </div>
                  <div className="profile-card">
                    <h4>Roles</h4>
                    <p>{auth.roles.join(", ") || "none"}</p>
                  </div>
                  <div className="profile-card">
                    <h4>IAM roles</h4>
                    <p>
                      {hasPermission("iam:read")
                        ? userIamRoles.join(", ") || "none"
                        : "Not available"}
                    </p>
                  </div>
                  <div className="profile-card">
                    <h4>Permissions</h4>
                    <p>{auth.permissions.join(", ") || "none"}</p>
                  </div>
                </div>
                <div className="profile-actions">
                  {accountUrl ? (
                    <a className="primary" href={accountUrl} target="_blank" rel="noreferrer">
                      Change password
                    </a>
                  ) : (
                    <span className="muted">IAM account console not configured.</span>
                  )}
                </div>
              </div>
            </section>
          )}

          {activeView === "help" && (
            <section className="view-grid">
              <div className="panel-card panel-card--wide">
                <h3>Support requests</h3>
                <p className="muted">
                  Raise a request with the operator team. If a support URL is configured, we will
                  open it in a new tab.
                </p>
                {supportUrl ? (
                  <a className="primary" href={supportUrl} target="_blank" rel="noreferrer">
                    Open support portal
                  </a>
                ) : (
                  <p className="muted">
                    Configure <code>VITE_SUPPORT_URL</code> to link a support portal.
                  </p>
                )}
              </div>
            </section>
          )}
        </div>
      </main>
      {workflowRunNotice && workflowNoticeMeta ? (
        <div
          className="modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-label="Workflow submission status"
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              setWorkflowRunNotice(null);
            }
          }}
        >
          <div className="modal-card">
            <div className="modal-header">
              <div>
                <h3>{workflowNoticeMeta.title}</h3>
                <p className="muted">{workflowRunNotice.workflowName}</p>
              </div>
              <button
                type="button"
                className="secondary"
                onClick={() => setWorkflowRunNotice(null)}
              >
                Close
              </button>
            </div>
            <div className="modal-body">
              <div className="modal-summary">
                <span className={`status-badge ${workflowNoticeMeta.statusClass}`}>
                  {workflowNoticeMeta.statusText}
                </span>
                <span className="modal-message">{workflowNoticeMeta.message}</span>
              </div>
              <div className="modal-details">
                <div className="modal-detail-row">
                  <span className="muted">Environment</span>
                  <span>{workflowRunNotice.environment}</span>
                </div>
                {workflowRunNotice.runId ? (
                  <div className="modal-detail-row">
                    <span className="muted">Run ID</span>
                    <span>{workflowRunNotice.runId}</span>
                  </div>
                ) : null}
                {workflowRunNotice.jobId ? (
                  <div className="modal-detail-row">
                    <span className="muted">Job ID</span>
                    <span>{workflowRunNotice.jobId}</span>
                  </div>
                ) : null}
                {workflowRunNotice.approvalId ? (
                  <div className="modal-detail-row">
                    <span className="muted">Approval ID</span>
                    <span>{workflowRunNotice.approvalId}</span>
                  </div>
                ) : null}
                {workflowRunNotice.approvalStatus ? (
                  <div className="modal-detail-row">
                    <span className="muted">Approval status</span>
                    <span>{workflowRunNotice.approvalStatus}</span>
                  </div>
                ) : null}
                <div className="modal-detail-row">
                  <span className="muted">Param keys</span>
                  <span>{workflowRunNotice.paramKeys.join(", ") || "none"}</span>
                </div>
                {workflowRunNotice.error ? (
                  <div className="modal-detail-row">
                    <span className="muted">Error</span>
                    <span>{workflowRunNotice.error}</span>
                  </div>
                ) : null}
              </div>
            </div>
            {workflowRunNotice.runId ? (
              <div className="modal-footer">
                <button
                  type="button"
                  className="primary"
                  onClick={() => {
                    setActiveView("workflows");
                    setFocusRunId(workflowRunNotice.runId ?? null);
                    setWorkflowRunNotice(null);
                  }}
                >
                  View in recent runs
                </button>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
      {selectedRun ? (
        <div
          className="modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-label="Workflow run details"
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              setSelectedRun(null);
            }
          }}
        >
          <div className="modal-card">
            <div className="modal-header">
              <div>
                <h3>Workflow run details</h3>
                <p className="muted">{selectedRun.workflow_name}</p>
              </div>
              <button
                type="button"
                className="secondary"
                onClick={() => setSelectedRun(null)}
              >
                Close
              </button>
            </div>
            <div className="modal-body">
              <div className="modal-summary">
                <span
                  className={`status-badge status-badge--${normalizeStatusClass(
                    selectedRun.status
                  )}`}
                >
                  {selectedRun.status}
                </span>
                <span className="modal-message">
                  {selectedRun.environment}
                  {selectedRun.approval_status
                    ? ` · approval ${selectedRun.approval_status}`
                    : ""}
                </span>
              </div>
              <div className="modal-details">
                <div className="modal-detail-row">
                  <span className="muted">Run ID</span>
                  <span>{selectedRun.id}</span>
                </div>
                {selectedRun.job_id ? (
                  <div className="modal-detail-row">
                    <span className="muted">Job ID</span>
                    <span>{selectedRun.job_id}</span>
                  </div>
                ) : null}
                <div className="modal-detail-row">
                  <span className="muted">Requested by</span>
                  <span>
                    {selectedRun.requested_by_name ??
                      selectedRun.requested_by ??
                      "unknown"}
                  </span>
                </div>
                <div className="modal-detail-row">
                  <span className="muted">Created</span>
                  <span>{new Date(selectedRun.created_at).toLocaleString()}</span>
                </div>
                {selectedRun.approval_id ? (
                  <div className="modal-detail-row">
                    <span className="muted">Approval ID</span>
                    <span>{selectedRun.approval_id}</span>
                  </div>
                ) : null}
                {selectedRun.approval_decided_at ? (
                  <div className="modal-detail-row">
                    <span className="muted">Approved at</span>
                    <span>{new Date(selectedRun.approval_decided_at).toLocaleString()}</span>
                  </div>
                ) : null}
                {selectedRun.approval_decided_by || selectedRun.approval_decided_by_name ? (
                  <div className="modal-detail-row">
                    <span className="muted">Approved by</span>
                    <span>
                      {selectedRun.approval_decided_by_name ??
                        selectedRun.approval_decided_by}
                    </span>
                  </div>
                ) : null}
                <div className="modal-detail-row">
                  <span className="muted">Parameters</span>
                  <span></span>
                </div>
                <pre className="modal-pre">
                  {selectedRun.params && Object.keys(selectedRun.params).length > 0
                    ? JSON.stringify(selectedRun.params, null, 2)
                    : "none"}
                </pre>
                <div className="modal-detail-row">
                  <span className="muted">Runtime timeline</span>
                  <span>{runtimeTimeline.length} event(s)</span>
                </div>
                {runtimeTimelineError ? (
                  <p className="muted">{runtimeTimelineError}</p>
                ) : null}
                {runtimeTimelineLoading ? <p className="muted">Loading timeline...</p> : null}
                {runtimeTimeline.length > 0 ? (
                  <div className="run-list">
                    {runtimeTimeline.map((event) => (
                      <div key={event.event_id} className="run-row run-row--stack">
                        <div className="summary-row">
                          <span
                            className={`status-badge status-badge--${normalizeStatusClass(
                              event.event_type
                            )}`}
                          >
                            {event.event_type}
                          </span>
                          <span className="muted">
                            {new Date(event.timestamp).toLocaleString()}
                          </span>
                        </div>
                        <div>{runtimeEventHeadline(event)}</div>
                        {Object.keys(event.payload ?? {}).length > 0 ? (
                          <pre className="modal-pre">{JSON.stringify(event.payload, null, 2)}</pre>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : null}
                {runtimeTimeline.some((item) => item.event_type === "approval.requested") &&
                hasPermission("approval:write") ? (
                  <div className="run-actions">
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => handleRuntimeRunDecision(selectedRun.id, "reject")}
                    >
                      Reject run
                    </button>
                    <button
                      type="button"
                      className="primary"
                      onClick={() => handleRuntimeRunDecision(selectedRun.id, "approve")}
                    >
                      Approve run
                    </button>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      ) : null}
      {selectedAgentRun ? (
        <div
          className="modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-label="Agent run details"
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              setSelectedAgentRun(null);
            }
          }}
        >
          <div className="modal-card">
            <div className="modal-header">
              <div>
                <h3>Agent run details</h3>
                <p className="muted">{selectedAgentRun.goal}</p>
              </div>
              <button
                type="button"
                className="secondary"
                onClick={() => setSelectedAgentRun(null)}
              >
                Close
              </button>
            </div>
            <div className="modal-body">
              <div className="modal-summary">
                <span
                  className={`status-badge status-badge--${normalizeStatusClass(
                    selectedAgentRun.status
                  )}`}
                >
                  {selectedAgentRun.status}
                </span>
                <span className="modal-message">
                  {selectedAgentRun.environment}
                  {selectedAgentRun.runtime?.status
                    ? ` · runtime ${selectedAgentRun.runtime.status}`
                    : ""}
                </span>
              </div>
              <div className="modal-details">
                <div className="modal-detail-row">
                  <span className="muted">Run ID</span>
                  <span>{selectedAgentRun.id}</span>
                </div>
                <div className="modal-detail-row">
                  <span className="muted">Requested by</span>
                  <span>
                    {selectedAgentRun.requested_by_name ??
                      selectedAgentRun.requested_by ??
                      "unknown"}
                  </span>
                </div>
                <div className="modal-detail-row">
                  <span className="muted">Created</span>
                  <span>{new Date(selectedAgentRun.created_at).toLocaleString()}</span>
                </div>
                <div className="modal-detail-row">
                  <span className="muted">Runtime timeline</span>
                  <span>{runtimeTimeline.length} event(s)</span>
                </div>
                {runtimeTimelineError ? (
                  <p className="muted">{runtimeTimelineError}</p>
                ) : null}
                {runtimeTimelineLoading ? <p className="muted">Loading timeline...</p> : null}
                {runtimeTimeline.length > 0 ? (
                  <div className="run-list">
                    {runtimeTimeline.map((event) => (
                      <div key={event.event_id} className="run-row run-row--stack">
                        <div className="summary-row">
                          <span
                            className={`status-badge status-badge--${normalizeStatusClass(
                              event.event_type
                            )}`}
                          >
                            {event.event_type}
                          </span>
                          <span className="muted">
                            {new Date(event.timestamp).toLocaleString()}
                          </span>
                        </div>
                        <div>{runtimeEventHeadline(event)}</div>
                        {Object.keys(event.payload ?? {}).length > 0 ? (
                          <pre className="modal-pre">{JSON.stringify(event.payload, null, 2)}</pre>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
