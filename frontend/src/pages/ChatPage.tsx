import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Empty,
  Segmented,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from "antd";
import { Input } from "antd";
import { Plus, RefreshCw, Search, Send, Square } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

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

const { Text, Title } = Typography;
const { TextArea } = Input;
const ACTIVE_STATUSES: RunStatus[] = ["queued", "running", "cancelling"];
const ALL_AGENTS = "__all_agents__";

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
  const [agentId, setAgentId] = useState<string>(ALL_AGENTS);
  const [chats, setChats] = useState<ChatSession[]>([]);
  const [chatId, setChatId] = useState<string>();
  const [detail, setDetail] = useState<ChatDetail>();
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [creating, setCreating] = useState(false);
  const [input, setInput] = useState("");
  const [activeRun, setActiveRun] = useState<AgentRun>();
  const [liveOutput, setLiveOutput] = useState("");
  const [liveToolEvents, setLiveToolEvents] = useState<LiveToolEvent[]>([]);
  const [liveDelegations, setLiveDelegations] = useState<LiveDelegationEvent[]>([]);
  const [streamState, setStreamState] = useState("未连接");
  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState<"all" | "console" | "wecom">("all");
  const eventSourceRef = useRef<EventSource | null>(null);
  const messageEndRef = useRef<HTMLDivElement | null>(null);
  const chatsRef = useRef<ChatSession[]>([]);
  const chatIdRef = useRef<string | undefined>(undefined);
  const visibleChats = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return chats.filter((chat) => {
      const sourceMatches =
        sourceFilter === "all" ||
        (sourceFilter === "console" && chat.channel === "console") ||
        (sourceFilter === "wecom" && chat.channel !== "console");
      if (!sourceMatches) return false;
      if (!normalized) return true;
      return [chat.title, chat.agent_name, chat.channel_name, chat.external_user_id]
        .filter(Boolean)
        .some((value) => String(value).toLocaleLowerCase().includes(normalized));
    });
  }, [chats, query, sourceFilter]);

  useEffect(() => {
    const loadAgents = async () => {
      try {
        const enabled = (await listAgents()).filter(
          (agent) => agent.status === "active",
        );
        setAgents(enabled);
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
    chatsRef.current = chats;
  }, [chats]);

  useEffect(() => {
    chatIdRef.current = chatId;
  }, [chatId]);

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [detail?.messages.length, liveOutput, liveToolEvents.length, liveDelegations.length]);

  useEffect(() => {
    eventSourceRef.current?.close();
    setActiveRun(undefined);
    setLiveOutput("");
    setLiveToolEvents([]);
    setLiveDelegations([]);
    setDetail(undefined);
    const load = async () => {
      setLoading(true);
      try {
        const nextChats = await listChats(
          agentId === ALL_AGENTS ? undefined : agentId,
        );
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
    let active = true;
    const poll = async () => {
      try {
        const nextChats = await listChats(
          agentId === ALL_AGENTS ? undefined : agentId,
        );
        if (!active) return;
        const selectedId = chatIdRef.current;
        const previous = chatsRef.current.find((chat) => chat.id === selectedId);
        const next = nextChats.find((chat) => chat.id === selectedId);
        chatsRef.current = nextChats;
        setChats(nextChats);
        if (
          selectedId &&
          next?.channel !== "console" &&
          previous?.updated_at !== next?.updated_at
        ) {
          await loadDetail(selectedId, true);
        }
      } catch {
        // Keep the current history visible during a temporary refresh failure.
      }
    };
    const timer = window.setInterval(() => void poll(), 4000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
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
    const nextChats = await listChats(
      selectedAgentId === ALL_AGENTS ? undefined : selectedAgentId,
    );
    chatsRef.current = nextChats;
    setChats(nextChats);
  };

  const loadDetail = async (selectedChatId: string, reconnect = false) => {
    setDetailLoading(true);
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
        if (running) {
          connectToRun(running, selectedChatId);
        } else {
          setStreamState("历史记录");
        }
      }
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setDetailLoading(false);
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
    if (agentId === ALL_AGENTS) {
      void message.info("请先选择一个具体 Agent 再新建网页会话");
      return;
    }
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
        title="没有可用 Agent"
        description="请先在 Blueprint 与 Agent 页面创建并启用一个 Agent。"
      />
    );
  }

  return (
    <div className="chat-console">
      <Card className="chat-sidebar" title={<span>统一会话 <Text type="secondary">{chats.length}</Text></span>}>
        <Select
          className="full-width chat-agent-select"
          value={agentId}
          loading={loading}
          options={[
            { value: ALL_AGENTS, label: "全部 Agent / 全部 Channel" },
            ...agents.map((agent) => ({ value: agent.id, label: agent.name })),
          ]}
          onChange={setAgentId}
        />
        <div className="chat-sidebar-actions">
          <Button
            type="primary"
            icon={<Plus size={16} />}
            loading={creating}
            disabled={agentId === ALL_AGENTS}
            onClick={() => void addChat()}
          >
            新建会话
          </Button>
          <Button
            aria-label="刷新会话"
            icon={<RefreshCw size={16} />}
            loading={loading}
            onClick={() => void refreshChats()}
          />
        </div>
        <Input
          allowClear
          prefix={<Search size={15} />}
          placeholder="搜索标题、Agent 或外部用户"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <Segmented
          block
          value={sourceFilter}
          options={[
            { value: "all", label: "全部" },
            { value: "console", label: "网页" },
            { value: "wecom", label: "企业微信" },
          ]}
          onChange={(value) => setSourceFilter(value as typeof sourceFilter)}
        />
        <div className="chat-session-list">
          {loading ? (
            <div className="sidebar-loading"><Spin size="small" /></div>
          ) : !visibleChats.length ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={query ? "没有匹配的会话" : "还没有会话"} />
          ) : (
            visibleChats.map((chat) => (
              <button
                type="button"
                key={chat.id}
                className={chat.id === chatId ? "chat-session active" : "chat-session"}
                onClick={() => setChatId(chat.id)}
              >
                <div className="chat-session-title">
                  <Text strong={chat.id === chatId} ellipsis={{ tooltip: chat.title }}>{chat.title}</Text>
                  <ChannelTag channel={chat.channel} />
                </div>
                <Text type="secondary" ellipsis>
                  {chat.agent_name} · {chat.channel_name ?? "网页控制台"}
                </Text>
                <Text type="secondary" className="chat-session-time">{formatTime(chat.updated_at)}</Text>
              </button>
            ))
          )}
        </div>
      </Card>

      <Card className="chat-main">
        {!chatId ? (
          <Empty description="新建或选择一个会话后开始交流" />
        ) : detailLoading && !detail ? (
          <Spin />
        ) : !detail ? (
          <Empty description="会话加载失败，请重新选择" />
        ) : (
          <>
            <header className="chat-header">
              <div>
                <Title level={4}>{detail.session.title}</Title>
                <Text type="secondary">
                  {detail.session.agent_name} · {sourceDescription(detail.session)} · 历史已持久化
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
                      <Text strong>
                        {item.role === "user"
                          ? detail.session.channel === "console"
                            ? "你"
                            : detail.session.external_user_id ?? "企业微信用户"
                          : detail.session.agent_name}
                      </Text>
                      {item.status === "partial" && <Tag color="orange">部分回答</Tag>}
                    </Space>
                    <div className="markdown-content">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{item.content}</ReactMarkdown>
                    </div>
                  </article>
                ))
              )}
              {activeRun && (
                <article className="message-bubble assistant streaming">
                  <Space>
                    <Text strong>{detail.session.agent_name}</Text>
                    <Tag color="processing">生成中</Tag>
                  </Space>
                  <div className="markdown-content">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {liveOutput || "正在读取人格与会话历史……"}
                    </ReactMarkdown>
                  </div>
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
              <div ref={messageEndRef} />
            </div>

            {detail.session.channel === "console" ? (
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
                      <Button danger icon={<Square size={14} />} onClick={() => void stop()}>
                        停止生成
                      </Button>
                    )}
                    <Button
                      type="primary"
                      icon={<Send size={15} />}
                      loading={sending}
                      disabled={!input.trim() || Boolean(activeRun)}
                      onClick={() => void send()}
                    >
                      发送
                    </Button>
                  </Space>
                </div>
              </div>
            ) : (
              <Alert
                type="info"
                showIcon
                title="这是外部 Channel 会话的只读镜像"
                description={`这里展示完整历史与运行审计。请从${detail.session.channel_name ?? "企业微信"}继续发送消息，网页不会伪造外部用户输入。`}
                action={
                  activeRun ? (
                    <Button danger size="small" onClick={() => void stop()}>
                      停止当前 Run
                    </Button>
                  ) : undefined
                }
              />
            )}

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

function ChannelTag({ channel }: { channel: ChatSession["channel"] }) {
  return channel === "console" ? (
    <Tag color="blue">网页</Tag>
  ) : (
    <Tag color="orange">企业微信</Tag>
  );
}

function sourceDescription(session: ChatSession): string {
  if (session.channel === "console") return "网页控制台";
  const mode = session.channel_kind === "wecom_bot" ? "智能机器人" : "自建应用";
  const channel = session.channel_name ?? "企业微信 Channel";
  const user = session.external_user_id ? ` · 用户 ${session.external_user_id}` : "";
  return `${channel} · ${mode}${user}`;
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
