import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Empty,
  List,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from "antd";
import { Input } from "antd";

import { listAgents, type Agent } from "../api/agents";
import {
  cancelRun,
  createChat,
  createRun,
  getChat,
  listChats,
  type AgentRun,
  type ChatDetail,
  type ChatSession,
  type DelegationStatus,
  type RunStatus,
  type ToolCallStatus,
} from "../api/chats";

const { Paragraph, Text, Title } = Typography;
const { TextArea } = Input;
const ACTIVE_STATUSES: RunStatus[] = ["queued", "running", "cancelling"];

interface LiveToolEvent {
  id: string;
  name: string;
  status: ToolCallStatus;
  message?: string;
}

interface LiveDelegationEvent {
  id: string;
  target: string;
  status: DelegationStatus;
  message?: string;
}

export default function ChatPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentId, setAgentId] = useState<string>();
  const [chats, setChats] = useState<ChatSession[]>([]);
  const [chatId, setChatId] = useState<string>();
  const [detail, setDetail] = useState<ChatDetail>();
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [creating, setCreating] = useState(false);
  const [input, setInput] = useState("");
  const [activeRun, setActiveRun] = useState<AgentRun>();
  const [liveOutput, setLiveOutput] = useState("");
  const [liveToolEvents, setLiveToolEvents] = useState<LiveToolEvent[]>([]);
  const [liveDelegations, setLiveDelegations] = useState<LiveDelegationEvent[]>([]);
  const [streamState, setStreamState] = useState("未连接");
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const loadAgents = async () => {
      try {
        const enabled = (await listAgents()).filter(
          (agent) => agent.status === "active",
        );
        setAgents(enabled);
        setAgentId((current) => current ?? enabled[0]?.id);
      } catch (reason) {
        void message.error(errorText(reason));
      } finally {
        setLoading(false);
      }
    };
    void loadAgents();
    return () => eventSourceRef.current?.close();
  }, []);

  useEffect(() => {
    eventSourceRef.current?.close();
    setActiveRun(undefined);
    setLiveOutput("");
    setLiveToolEvents([]);
    setLiveDelegations([]);
    setDetail(undefined);
    if (!agentId) {
      setChats([]);
      setChatId(undefined);
      return;
    }
    const load = async () => {
      setLoading(true);
      try {
        const nextChats = await listChats(agentId);
        setChats(nextChats);
        setChatId((current) =>
          nextChats.some((chat) => chat.id === current)
            ? current
            : nextChats[0]?.id,
        );
      } catch (reason) {
        void message.error(errorText(reason));
      } finally {
        setLoading(false);
      }
    };
    void load();
  }, [agentId]);

  useEffect(() => {
    eventSourceRef.current?.close();
    setActiveRun(undefined);
    setLiveOutput("");
    setLiveToolEvents([]);
    setLiveDelegations([]);
    if (!chatId) {
      setDetail(undefined);
      return;
    }
    void loadDetail(chatId, true);
  }, [chatId]);

  const refreshChats = async (selectedAgentId = agentId) => {
    if (!selectedAgentId) return;
    setChats(await listChats(selectedAgentId));
  };

  const loadDetail = async (selectedChatId: string, reconnect = false) => {
    try {
      const nextDetail = await getChat(selectedChatId);
      setDetail(nextDetail);
      if (reconnect) {
        const running = [...nextDetail.runs]
          .reverse()
          .find(
            (run) =>
              run.parent_run_id === null && ACTIVE_STATUSES.includes(run.status),
          );
        if (running) connectToRun(running, selectedChatId);
      }
    } catch (reason) {
      void message.error(errorText(reason));
    }
  };

  const connectToRun = (run: AgentRun, selectedChatId: string) => {
    eventSourceRef.current?.close();
    setActiveRun(run);
    setLiveOutput("");
    setLiveToolEvents([]);
    setLiveDelegations([]);
    setStreamState("正在连接 SSE");
    const source = new EventSource(`/api/runs/${run.id}/events`);
    eventSourceRef.current = source;

    source.addEventListener("run.started", () => {
      setStreamState("模型正在生成");
      setActiveRun((current) =>
        current ? { ...current, status: "running" } : current,
      );
    });
    source.addEventListener("run.delta", (event) => {
      const data = parseEvent(event);
      if (typeof data.content === "string") {
        setLiveOutput((current) => current + data.content);
      }
    });
    source.addEventListener("tool.requested", (event) => {
      updateLiveTool(event, "requested");
    });
    source.addEventListener("tool.started", (event) => {
      updateLiveTool(event, "running");
    });
    source.addEventListener("tool.completed", (event) => {
      updateLiveTool(event, "completed");
    });
    source.addEventListener("tool.failed", (event) => {
      updateLiveTool(event, "failed");
    });
    source.addEventListener("tool.rejected", (event) => {
      updateLiveTool(event, "rejected");
    });
    source.addEventListener("delegation.started", (event) => {
      updateLiveDelegation(event, "running");
    });
    source.addEventListener("delegation.completed", (event) => {
      updateLiveDelegation(event, "completed");
    });
    source.addEventListener("delegation.failed", (event) => {
      updateLiveDelegation(event, "failed");
    });
    source.addEventListener("run.completed", () => {
      finishStream(source, selectedChatId, "已完成");
    });
    source.addEventListener("run.cancelled", () => {
      finishStream(source, selectedChatId, "已取消");
    });
    source.addEventListener("run.failed", (event) => {
      const data = parseEvent(event);
      if (typeof data.message === "string") void message.error(data.message);
      finishStream(source, selectedChatId, "运行失败");
    });
    source.onerror = () => {
      if (source.readyState !== EventSource.CLOSED) setStreamState("SSE 断线重连中");
    };
  };

  const updateLiveTool = (event: Event, status: ToolCallStatus) => {
    const data = parseEvent(event);
    const id = typeof data.tool_call_id === "string" ? data.tool_call_id : "";
    const name = typeof data.tool_name === "string" ? data.tool_name : "unknown";
    if (!id) return;
    setLiveToolEvents((current) => {
      const next = current.filter((item) => item.id !== id);
      return [
        ...next,
        {
          id,
          name,
          status,
          message: typeof data.message === "string" ? data.message : undefined,
        },
      ];
    });
    if (status === "running") setStreamState(`正在执行 Tool：${name}`);
    if (status === "completed") setStreamState("Tool 已完成，模型继续生成");
  };

  const updateLiveDelegation = (event: Event, status: DelegationStatus) => {
    const data = parseEvent(event);
    const id = typeof data.delegation_id === "string" ? data.delegation_id : "";
    const target =
      typeof data.target_agent_name === "string"
        ? data.target_agent_name
        : typeof data.target_agent_id === "string"
          ? data.target_agent_id
          : "成员 Agent";
    if (!id) return;
    setLiveDelegations((current) => [
      ...current.filter((item) => item.id !== id),
      {
        id,
        target,
        status,
        message: typeof data.message === "string" ? data.message : undefined,
      },
    ]);
    if (status === "running") setStreamState(`正在等待成员：${target}`);
    if (status === "completed") setStreamState("成员已返回，协调 Agent 正在汇总");
  };

  const finishStream = (
    source: EventSource,
    selectedChatId: string,
    state: string,
  ) => {
    source.close();
    if (eventSourceRef.current === source) eventSourceRef.current = null;
    setStreamState(state);
    setActiveRun(undefined);
    setLiveOutput("");
    setLiveToolEvents([]);
    setLiveDelegations([]);
    void loadDetail(selectedChatId);
    void refreshChats();
  };

  const addChat = async () => {
    if (!agentId) return;
    setCreating(true);
    try {
      const chat = await createChat(agentId);
      await refreshChats(agentId);
      setChatId(chat.id);
      void message.success("新会话已创建");
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setCreating(false);
    }
  };

  const send = async () => {
    const content = input.trim();
    if (!chatId || !content || activeRun) return;
    setSending(true);
    try {
      const run = await createRun(chatId, content);
      setInput("");
      await loadDetail(chatId);
      connectToRun(run, chatId);
      await refreshChats();
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setSending(false);
    }
  };

  const stop = async () => {
    if (!activeRun) return;
    try {
      setActiveRun({ ...activeRun, status: "cancelling" });
      setStreamState("正在请求停止");
      await cancelRun(activeRun.id);
    } catch (reason) {
      void message.error(errorText(reason));
    }
  };

  if (!agents.length && !loading) {
    return (
      <Alert
        type="warning"
        showIcon
        message="没有可用 Agent"
        description="请先在 Blueprint 与 Agent 页面创建并启用一个 Agent。"
      />
    );
  }

  return (
    <div className="chat-console">
      <Card className="chat-sidebar" title="Console 会话">
        <Text type="secondary">当前 Agent</Text>
        <Select
          className="full-width chat-agent-select"
          value={agentId}
          loading={loading}
          options={agents.map((agent) => ({ value: agent.id, label: agent.name }))}
          onChange={setAgentId}
        />
        <Button
          className="full-width"
          type="primary"
          loading={creating}
          disabled={!agentId}
          onClick={() => void addChat()}
        >
          新建会话
        </Button>
        <List
          className="chat-session-list"
          loading={loading}
          locale={{ emptyText: "这个 Agent 还没有会话" }}
          dataSource={chats}
          renderItem={(chat) => (
            <List.Item
              className={chat.id === chatId ? "chat-session active" : "chat-session"}
              onClick={() => setChatId(chat.id)}
            >
              <div>
                <Text strong={chat.id === chatId}>{chat.title}</Text>
                <Text type="secondary">{formatTime(chat.updated_at)}</Text>
              </div>
            </List.Item>
          )}
        />
      </Card>

      <Card className="chat-main">
        {!chatId ? (
          <Empty description="新建或选择一个会话后开始交流" />
        ) : !detail ? (
          <Spin />
        ) : (
          <>
            <header className="chat-header">
              <div>
                <Title level={4}>{detail.session.title}</Title>
                <Text type="secondary">
                  {detail.session.agent_name} · console · 历史已持久化
                </Text>
              </div>
              <Space wrap>
                {activeRun && <RunStatusTag status={activeRun.status} />}
                <Tag>{streamState}</Tag>
              </Space>
            </header>

            <div className="message-list">
              {!detail.messages.length && !liveOutput ? (
                <Empty description="发送第一条消息，Agent 会读取自己的 Workspace" />
              ) : (
                detail.messages.map((item) => (
                  <article key={item.id} className={`message-bubble ${item.role}`}>
                    <Space>
                      <Text strong>{item.role === "user" ? "你" : detail.session.agent_name}</Text>
                      {item.status === "partial" && <Tag color="orange">部分回答</Tag>}
                    </Space>
                    <Paragraph>{item.content}</Paragraph>
                  </article>
                ))
              )}
              {activeRun && (
                <article className="message-bubble assistant streaming">
                  <Space>
                    <Text strong>{detail.session.agent_name}</Text>
                    <Tag color="processing">生成中</Tag>
                  </Space>
                  <Paragraph>{liveOutput || "正在读取人格与会话历史……"}</Paragraph>
                </article>
              )}
              {!!liveToolEvents.length && (
                <div className="tool-live-panel">
                  <Text strong>当前 Run 的 Tool 调用</Text>
                  {liveToolEvents.map((item) => (
                    <div key={item.id} className="tool-row">
                      <Text code>{item.name}</Text>
                      <ToolStatusTag status={item.status} />
                      <Text type="secondary">{item.message ?? "服务端已记录审计事件"}</Text>
                    </div>
                  ))}
                </div>
              )}
              {!!liveDelegations.length && (
                <div className="delegation-live-panel">
                  <Text strong>当前 Run 的 Agent 委派</Text>
                  {liveDelegations.map((item) => (
                    <div key={item.id} className="tool-row">
                      <Text>{item.target}</Text>
                      <DelegationStatusTag status={item.status} />
                      <Text type="secondary">{item.message ?? "子 Run 正在独立执行"}</Text>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="chat-composer">
              <TextArea
                value={input}
                disabled={Boolean(activeRun)}
                placeholder="输入消息；⌘/Ctrl + Enter 发送"
                autoSize={{ minRows: 3, maxRows: 8 }}
                maxLength={20_000}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                    event.preventDefault();
                    void send();
                  }
                }}
              />
              <div className="composer-actions">
                <Text type="secondary">
                  {activeRun
                    ? `Run ${activeRun.id} · ${activeRun.model_name}`
                    : "刷新页面后仍可恢复消息和未结束 Run"}
                </Text>
                <Space>
                  {activeRun && (
                    <Button danger onClick={() => void stop()}>
                      停止生成
                    </Button>
                  )}
                  <Button
                    type="primary"
                    loading={sending}
                    disabled={!input.trim() || Boolean(activeRun)}
                    onClick={() => void send()}
                  >
                    发送
                  </Button>
                </Space>
              </div>
            </div>

            {!!detail.runs.length && (
              <div className="run-audit">
                <Text strong>最近 Run</Text>
                {[...detail.runs].reverse().slice(0, 4).map((run) => (
                  <div key={run.id} className="run-row">
                    <Text code>{run.id.slice(0, 8)}</Text>
                    <RunStatusTag status={run.status} />
                    <Text>{run.model_name}</Text>
                    <Text type="secondary">
                      {run.duration_ms === null ? "—" : `${run.duration_ms} ms`}
                    </Text>
                  </div>
                ))}
              </div>
            )}
            {!!detail.tool_calls.length && (
              <div className="run-audit">
                <Text strong>Tool 调用审计</Text>
                {[...detail.tool_calls].reverse().slice(0, 8).map((toolCall) => (
                  <div key={toolCall.id} className="tool-row">
                    <Text code>{toolCall.tool_name}</Text>
                    <ToolStatusTag status={toolCall.status} />
                    <Text type="secondary">
                      {toolCall.error_message ?? JSON.stringify(toolCall.arguments)}
                    </Text>
                    <Text type="secondary">
                      {toolCall.duration_ms === null ? "—" : `${toolCall.duration_ms} ms`}
                    </Text>
                  </div>
                ))}
              </div>
            )}
            {!!detail.delegations.length && (
              <div className="run-audit">
                <Text strong>Agent 委派审计</Text>
                {[...detail.delegations].reverse().slice(0, 8).map((delegation) => (
                  <div key={delegation.id} className="delegation-row">
                    <Text>{delegation.source_agent_name} → {delegation.target_agent_name}</Text>
                    <DelegationStatusTag status={delegation.status} />
                    <Text type="secondary" ellipsis={{ tooltip: delegation.task }}>
                      {delegation.task}
                    </Text>
                    <Text type="secondary">深度 {delegation.depth}</Text>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </Card>
    </div>
  );
}

function RunStatusTag({ status }: { status: RunStatus }) {
  const color: Record<RunStatus, string> = {
    queued: "default",
    running: "processing",
    cancelling: "warning",
    completed: "success",
    failed: "error",
    cancelled: "orange",
  };
  return <Tag color={color[status]}>{status}</Tag>;
}

function ToolStatusTag({ status }: { status: ToolCallStatus }) {
  const color: Record<ToolCallStatus, string> = {
    requested: "default",
    running: "processing",
    completed: "success",
    failed: "error",
    rejected: "warning",
  };
  return <Tag color={color[status]}>{status}</Tag>;
}

function DelegationStatusTag({ status }: { status: DelegationStatus }) {
  const color: Record<DelegationStatus, string> = {
    requested: "default",
    running: "processing",
    completed: "success",
    failed: "error",
    cancelled: "orange",
  };
  return <Tag color={color[status]}>{status}</Tag>;
}

function parseEvent(event: Event): Record<string, unknown> {
  if (!(event instanceof MessageEvent)) return {};
  try {
    return JSON.parse(String(event.data)) as Record<string, unknown>;
  } catch {
    return {};
  }
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function errorText(reason: unknown): string {
  return reason instanceof Error ? reason.message : "发生未知错误";
}
