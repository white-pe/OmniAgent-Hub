export interface HealthResponse {
  name: string;
  version: string;
  environment: string;
  status: "ok" | "degraded";
  database: "ok" | "unavailable";
}

export interface ProbeResult {
  ok: boolean;
  status: number | null;
  latencyMs: number;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await apiFetch("/api/health");
  if (!response.ok) {
    throw new Error(`健康检查失败：HTTP ${response.status}`);
  }
  return response.json() as Promise<HealthResponse>;
}

export async function probeHealth(path: "/api/health/live" | "/api/health/ready"): Promise<ProbeResult> {
  const startedAt = performance.now();
  try {
    const response = await apiFetch(path, { cache: "no-store" });
    return {
      ok: response.ok,
      status: response.status,
      latencyMs: Math.round(performance.now() - startedAt),
    };
  } catch {
    return {
      ok: false,
      status: null,
      latencyMs: Math.round(performance.now() - startedAt),
    };
  }
}
import { apiFetch } from "./http";
