export interface Skill {
  id: string;
  agent_id: string;
  name: string;
  description: string;
  path: string;
  content: string;
  enabled: boolean;
  channel_scope: string[];
  config: Record<string, unknown>;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface SkillInput {
  name: string;
  description: string;
  content: string;
  enabled?: boolean;
  channel_scope?: ("console" | "wecom")[];
  config?: Record<string, unknown>;
}

export async function listSkills(agentId: string): Promise<Skill[]> {
  return requestJson<Skill[]>(`/api/agents/${agentId}/skills`);
}

export async function createSkill(
  agentId: string,
  input: SkillInput,
): Promise<Skill> {
  return requestJson<Skill>(`/api/agents/${agentId}/skills`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function updateSkill(
  agentId: string,
  skill: Skill,
  input: Pick<SkillInput, "description" | "content" | "channel_scope">,
): Promise<Skill> {
  return requestJson<Skill>(`/api/agents/${agentId}/skills/${skill.name}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expected_version: skill.version, ...input }),
  });
}

export async function toggleSkill(agentId: string, name: string): Promise<Skill> {
  return requestJson<Skill>(`/api/agents/${agentId}/skills/${name}/toggle`, {
    method: "POST",
  });
}

export async function deleteSkill(agentId: string, name: string): Promise<void> {
  const response = await apiFetch(`/api/agents/${agentId}/skills/${name}`, {
    method: "DELETE",
  });
  if (!response.ok) throw new Error(await errorMessage(response));
}

import { apiFetch, errorMessage, requestJson } from "./http";
