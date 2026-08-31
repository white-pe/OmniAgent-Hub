export interface ProviderModel {
  id: string;
  model_name: string;
  display_name: string;
  capabilities: Record<string, unknown>;
  enabled: boolean;
}

export interface Provider {
  id: string;
  name: string;
  kind: string;
  base_url: string;
  enabled: boolean;
  configured: boolean;
  created_at: string;
  updated_at: string;
  models: ProviderModel[];
}

export interface ProviderInput {
  name: string;
  base_url: string;
  api_key?: string;
  enabled?: boolean;
  models: Array<{ model_name: string; display_name?: string }>;
}

export interface ProviderTestResult {
  ok: boolean;
  model: string;
  latency_ms: number;
  reply_preview: string;
}

export type StreamEvent =
  | { event: "start"; data: { model: string } }
  | { event: "delta"; data: { content: string } }
  | { event: "done"; data: { model: string } }
  | { event: "error"; data: { message: string } };

export async function listProviders(): Promise<Provider[]> {
  return requestJson<Provider[]>("/api/providers");
}

export async function createProvider(input: ProviderInput): Promise<Provider> {
  return requestJson<Provider>("/api/providers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function updateProvider(
  providerId: string,
  input: Partial<ProviderInput>,
): Promise<Provider> {
  return requestJson<Provider>(`/api/providers/${providerId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function deleteProvider(providerId: string): Promise<void> {
  const response = await apiFetch(`/api/providers/${providerId}`, { method: "DELETE" });
  if (!response.ok) throw new Error(await errorMessage(response));
}

export async function testProvider(
  providerId: string,
  modelId?: string,
): Promise<ProviderTestResult> {
  return requestJson<ProviderTestResult>(`/api/providers/${providerId}/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id: modelId }),
  });
}

export async function streamProviderChat(
  providerId: string,
  input: {
    model_id: string;
    prompt: string;
    system_prompt?: string;
    temperature?: number;
  },
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  const response = await apiFetch(`/api/providers/${providerId}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) throw new Error(await errorMessage(response));
  if (!response.body) throw new Error("浏览器没有收到流式响应体");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replaceAll("\r\n", "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const event = parseSseBlock(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      if (event) onEvent(event);
      boundary = buffer.indexOf("\n\n");
    }
    if (done) break;
  }
}

function parseSseBlock(block: string): StreamEvent | null {
  let eventName = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) eventName = line.slice(6).trim();
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (!dataLines.length) return null;
  const data = JSON.parse(dataLines.join("\n")) as Record<string, string>;
  if (!["start", "delta", "done", "error"].includes(eventName)) return null;
  return { event: eventName, data } as StreamEvent;
}

import { apiFetch, errorMessage, requestJson } from "./http";
