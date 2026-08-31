import type { Agent } from "./agents";
import { jsonRequest, requestJson } from "./http";

export type BlueprintTool =
  | "read_workspace_file"
  | "search_workspace_files"
  | "delegate_to_agent";
export type BlueprintModelHint = "fast" | "balanced" | "reasoning";
export type BlueprintStatus = "draft" | "cancelled" | "applied" | "expired";

export interface AgentBlueprint {
  name: string;
  description: string;
  role: string;
  goals: string[];
  tone: string;
  rules: string[];
  requested_tools: BlueprintTool[];
  requested_skills: string[];
  model_hint: BlueprintModelHint;
  is_coordinator: boolean;
}

export interface BlueprintDraft {
  draft_id: string;
  request_text: string;
  blueprint: AgentBlueprint;
  warnings: string[];
  status: BlueprintStatus;
  source_provider_id: string;
  source_provider_name: string;
  source_model_id: string;
  source_model_name: string;
  applied_agent_id: string | null;
  created_at: string;
  expires_at: string;
}

export interface BlueprintGenerateInput {
  description: string;
  provider_id: string;
  model_id: string;
}

export interface BlueprintApplyInput {
  draft_id: string;
  blueprint: AgentBlueprint;
  provider_id: string;
  model_id: string;
}

export async function generateBlueprint(
  input: BlueprintGenerateInput,
): Promise<BlueprintDraft> {
  return requestJson<BlueprintDraft>(
    "/api/agent-blueprints/generate",
    jsonRequest("POST", input),
  );
}

export async function cancelBlueprint(draftId: string): Promise<BlueprintDraft> {
  return requestJson<BlueprintDraft>(`/api/agent-blueprints/${draftId}/cancel`, {
    method: "POST",
  });
}

export async function applyBlueprint(input: BlueprintApplyInput): Promise<Agent> {
  return requestJson<Agent>(
    "/api/agents/from-blueprint",
    jsonRequest("POST", input),
  );
}
