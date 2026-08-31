import { apiFetch, errorMessage, jsonRequest, requestJson } from "./http";

export interface AuthStatus {
  auth_enabled: boolean;
  authenticated: boolean;
  username: string | null;
}

export async function getAuthStatus(): Promise<AuthStatus> {
  return requestJson<AuthStatus>("/api/auth/status");
}

export async function login(password: string): Promise<AuthStatus> {
  return requestJson<AuthStatus>(
    "/api/auth/login",
    jsonRequest("POST", { password }),
  );
}

export async function logout(): Promise<void> {
  const response = await apiFetch("/api/auth/logout", { method: "POST" });
  if (!response.ok) throw new Error(await errorMessage(response));
}
