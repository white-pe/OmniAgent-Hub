export interface ToolAssignment {
  name: string;
  description: string;
  enabled: boolean;
  input_schema: Record<string, unknown>;
}

export async function listTools(agentId: string): Promise<ToolAssignment[]> {
  return requestJson<ToolAssignment[]>(`/api/agents/${agentId}/tools`);
}

export async function toggleTool(
  agentId: string,
  toolName: string,
): Promise<ToolAssignment> {
  return requestJson<ToolAssignment>(
    `/api/agents/${agentId}/tools/${toolName}/toggle`,
    { method: "POST" },
  );
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    try {
      const body = (await response.json()) as { detail?: string };
      throw new Error(body.detail ?? `请求失败：HTTP ${response.status}`);
    } catch (reason) {
      if (reason instanceof Error) throw reason;
      throw new Error(`请求失败：HTTP ${response.status}`);
    }
  }
  return response.json() as Promise<T>;
}
