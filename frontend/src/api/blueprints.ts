import type { Agent } from "./agents";

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
