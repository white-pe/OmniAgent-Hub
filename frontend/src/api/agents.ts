export type AgentStatus = "active" | "disabled";
export type WorkspaceFilename = "AGENTS.md" | "SOUL.md" | "PROFILE.md" | "MEMORY.md";

export interface Agent {
  id: string;
  name: string;
  description: string;
  status: AgentStatus;
  workspace_path: string;
  provider_id: string;
  provider_name: string;
  model_id: string;
  model_name: string;
  is_coordinator: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface AgentCreateInput {
  name: string;
  description: string;
  provider_id: string;
  model_id: string;
  is_coordinator: boolean;
}

export interface AgentUpdateInput {
  expected_version: number;
  name?: string;
  description?: string;
  provider_id?: string;
  model_id?: string;
  is_coordinator?: boolean;
}

export interface WorkspaceFile {
  agent_id: string;
  filename: WorkspaceFilename;
  content: string;
  agent_version: number;
}

export async function listAgents(): Promise<Agent[]> {
  return requestJson<Agent[]>("/api/agents");
}

export async function createAgent(input: AgentCreateInput): Promise<Agent> {
  return requestJson<Agent>("/api/agents", jsonRequest("POST", input));
}

export async function updateAgent(
  agentId: string,
  input: AgentUpdateInput,
): Promise<Agent> {
  return requestJson<Agent>(`/api/agents/${agentId}`, jsonRequest("PUT", input));
}

export async function toggleAgent(agentId: string): Promise<Agent> {
  return requestJson<Agent>(`/api/agents/${agentId}/toggle`, { method: "POST" });
}

export async function deleteAgent(agentId: string): Promise<void> {
  const response = await fetch(`/api/agents/${agentId}`, { method: "DELETE" });
  if (!response.ok) throw new Error(await errorMessage(response));
}

export async function getWorkspaceFile(
  agentId: string,
  filename: WorkspaceFilename,
): Promise<WorkspaceFile> {
  return requestJson<WorkspaceFile>(`/api/agents/${agentId}/files/${filename}`);
}

export async function updateWorkspaceFile(
  agentId: string,
  filename: WorkspaceFilename,
  content: string,
  expectedVersion: number,
): Promise<WorkspaceFile> {
  return requestJson<WorkspaceFile>(
    `/api/agents/${agentId}/files/${filename}`,
    jsonRequest("PUT", { content, expected_version: expectedVersion }),
  );
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
    const body = (await response.json()) as { detail?: string };
    return body.detail ?? `请求失败：HTTP ${response.status}`;
  } catch {
    return `请求失败：HTTP ${response.status}`;
  }
}
