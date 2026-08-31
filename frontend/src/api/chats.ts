export type RunStatus =
  | "queued"
  | "running"
  | "cancelling"
  | "completed"
  | "failed"
  | "cancelled";

export interface ChatSession {
  id: string;
  agent_id: string;
  agent_name: string;
  title: string;
  channel: "console";
  status: "active" | "archived";
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  session_id: string;
  run_id: string | null;
  role: "user" | "assistant";
  content: string;
  status: "final" | "partial";
  sequence: number;
  created_at: string;
}

export interface AgentRun {
  id: string;
  session_id: string;
  agent_id: string;
  provider_id: string;
  model_id: string;
  model_name: string;
  status: RunStatus;
  output_text: string;
  error_message: string | null;
  cancel_requested: boolean;
  input_tokens: number | null;
  output_tokens: number | null;
  duration_ms: number | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export type ToolCallStatus =
  | "requested"
  | "running"
  | "completed"
  | "failed"
  | "rejected";

export interface ToolCall {
  id: string;
  run_id: string;
  provider_call_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  status: ToolCallStatus;
  result: Record<string, unknown> | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  created_at: string;
}

export interface ChatDetail {
  session: ChatSession;
  messages: ChatMessage[];
  runs: AgentRun[];
  tool_calls: ToolCall[];
}

export async function listChats(agentId?: string): Promise<ChatSession[]> {
  const query = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : "";
  return requestJson<ChatSession[]>(`/api/chats${query}`);
}

export async function createChat(agentId: string): Promise<ChatSession> {
  return requestJson<ChatSession>(
    "/api/chats",
    jsonRequest("POST", { agent_id: agentId }),
  );
}

export async function getChat(chatId: string): Promise<ChatDetail> {
  return requestJson<ChatDetail>(`/api/chats/${chatId}`);
}

export async function createRun(chatId: string, content: string): Promise<AgentRun> {
  return requestJson<AgentRun>(
    `/api/chats/${chatId}/runs`,
    jsonRequest("POST", { content }),
  );
}

export async function getRun(runId: string): Promise<AgentRun> {
  return requestJson<AgentRun>(`/api/runs/${runId}`);
}

export async function cancelRun(runId: string): Promise<AgentRun> {
  return requestJson<AgentRun>(`/api/runs/${runId}/cancel`, { method: "POST" });
}

function jsonRequest(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error(await errorMessage(response));
  return response.json() as Promise<T>;
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as {
      detail?: string | Array<{ msg?: string }>;
    };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail.map((item) => item.msg ?? "字段校验失败").join("；");
    }
    return `请求失败：HTTP ${response.status}`;
  } catch {
    return `请求失败：HTTP ${response.status}`;
  }
}
