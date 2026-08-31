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

import { requestJson } from "./http";
