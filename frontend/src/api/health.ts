export interface HealthResponse {
  name: string;
  version: string;
  environment: string;
  status: "ok" | "degraded";
  database: "ok" | "unavailable";
}

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch("/api/health");
  if (!response.ok) {
    throw new Error(`健康检查失败：HTTP ${response.status}`);
  }
  return response.json() as Promise<HealthResponse>;
}
