export type ChannelStatus = "active" | "disabled";

export interface Channel {
  id: string;
  name: string;
  kind: "wecom";
  agent_id: string;
  agent_name: string;
  status: ChannelStatus;
  corp_id: string;
  wecom_agent_id: number;
  callback_path: string;
  has_secrets: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface WeComChannelInput {
  name: string;
  agent_id: string;
  corp_id: string;
  wecom_agent_id: number;
  token: string;
  encoding_aes_key: string;
  corp_secret: string;
}

export interface ChannelMessage {
  id: string;
  channel_id: string;
  external_conversation_id: string;
  external_user_id: string;
  external_message_id: string;
  direction: "inbound" | "outbound";
  content: string;
  status: string;
  chat_session_id: string;
  run_id: string | null;
  attempts: number;
  error_message: string | null;
  delivered_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface DebugInboundInput {
  external_user_id: string;
  external_conversation_id?: string;
  external_message_id?: string;
  content: string;
}

export interface ChannelIngressResult {
  duplicate: boolean;
  channel_message_id: string;
  chat_session_id: string;
  run_id: string | null;
  outbound_message_id: string | null;
}

export async function listChannels(): Promise<Channel[]> {
  return requestJson<Channel[]>("/api/channels");
}

export async function createChannel(input: WeComChannelInput): Promise<Channel> {
  return requestJson<Channel>("/api/channels", jsonRequest("POST", input));
}

export async function updateChannel(
  channel: Channel,
  input: Pick<
    WeComChannelInput,
    "name" | "agent_id" | "corp_id" | "wecom_agent_id"
  >,
): Promise<Channel> {
  return requestJson<Channel>(
    `/api/channels/${channel.id}`,
    jsonRequest("PUT", { ...input, expected_version: channel.version }),
  );
}

export async function rotateChannelSecrets(
  channel: Channel,
  input: Pick<
    WeComChannelInput,
    "token" | "encoding_aes_key" | "corp_secret"
  >,
): Promise<Channel> {
  return requestJson<Channel>(
    `/api/channels/${channel.id}/secrets`,
    jsonRequest("PUT", { ...input, expected_version: channel.version }),
  );
}

export async function setChannelStatus(
  channel: Channel,
  status: ChannelStatus,
): Promise<Channel> {
  return requestJson<Channel>(
    `/api/channels/${channel.id}/status`,
    jsonRequest("PUT", { status, expected_version: channel.version }),
  );
}

export async function deleteChannel(channelId: string): Promise<void> {
  const response = await fetch(`/api/channels/${channelId}`, { method: "DELETE" });
  if (!response.ok) throw new Error(await errorMessage(response));
}

export async function listChannelMessages(
  channelId: string,
): Promise<ChannelMessage[]> {
  return requestJson<ChannelMessage[]>(`/api/channels/${channelId}/messages`);
}

export async function sendDebugInbound(
  channelId: string,
  input: DebugInboundInput,
): Promise<ChannelIngressResult> {
  return requestJson<ChannelIngressResult>(
    `/api/channels/${channelId}/debug-inbound`,
    jsonRequest("POST", input),
  );
}

export async function retryChannelMessage(messageId: string): Promise<void> {
  await requestJson(`/api/channels/messages/${messageId}/retry`, { method: "POST" });
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
