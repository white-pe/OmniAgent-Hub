export type TeamStatus = "active" | "disabled";

export interface TeamMember {
  agent_id: string;
  agent_name: string;
  role: "coordinator" | "member";
  agent_status: "active" | "disabled";
}

export interface Team {
  id: string;
  name: string;
  description: string;
  coordinator_agent_id: string;
  coordinator_agent_name: string;
  status: TeamStatus;
  members: TeamMember[];
  version: number;
  created_at: string;
  updated_at: string;
}

export interface TeamInput {
  name: string;
  description: string;
  coordinator_agent_id: string;
  member_agent_ids: string[];
}

export async function listTeams(): Promise<Team[]> {
  return requestJson<Team[]>("/api/teams");
}

export async function createTeam(input: TeamInput): Promise<Team> {
  return requestJson<Team>("/api/teams", jsonRequest("POST", input));
}

export async function updateTeam(
  team: Team,
  input: TeamInput,
): Promise<Team> {
  return requestJson<Team>(
    `/api/teams/${team.id}`,
    jsonRequest("PUT", { ...input, expected_version: team.version }),
  );
}

export async function toggleTeam(teamId: string): Promise<Team> {
  return requestJson<Team>(`/api/teams/${teamId}/toggle`, { method: "POST" });
}

export async function deleteTeam(teamId: string): Promise<void> {
  const response = await fetch(`/api/teams/${teamId}`, { method: "DELETE" });
  if (!response.ok) throw new Error(await errorMessage(response));
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
