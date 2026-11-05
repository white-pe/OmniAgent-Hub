import type { ReactNode } from "react";
import { Alert, Button, Card, Skeleton, Tag, Typography, message } from "antd";
import {
  Activity,
  Bot,
  Boxes,
  Cable,
  Check,
  CircleAlert,
  MessageSquareText,
  Network,
  RefreshCw,
  Server,
  BookOpen,
} from "lucide-react";
import { useEffect, useState } from "react";

import { listAgents, type Agent } from "../api/agents";
import { listChannels, type Channel } from "../api/channels";
import { listChats, type ChatSession } from "../api/chats";
import { fetchHealth, type HealthResponse } from "../api/health";
import { listProviders, type Provider } from "../api/providers";
import { listTeams, type Team } from "../api/teams";
import { knowledgeApi, type RagStatus } from "../api/knowledge";

const { Text, Title } = Typography;

interface Snapshot {
  agents: Agent[];
  channels: Channel[];
  chats: ChatSession[];
  health: HealthResponse;
  providers: Provider[];
  teams: Team[];
  knowledge: RagStatus;
}

export default function OverviewPage() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      const [agents, channels, chats, health, providers, teams, knowledge] = await Promise.all([
        listAgents(),
        listChannels(),
        listChats(),
        fetchHealth(),
        listProviders(),
        listTeams(),
        knowledgeApi.status(),
      ]);
      setSnapshot({ agents, channels, chats, health, providers, teams, knowledge });
      setUpdatedAt(new Date());
    } catch (reason) {
      void message.error(reason instanceof Error ? reason.message : "总览数据加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  if (!snapshot && loading) return <Skeleton active paragraph={{ rows: 8 }} />;
  if (!snapshot) {
    return (
      <Alert
        type="error"
        showIcon
        title="无法读取系统总览"
        action={<Button onClick={() => void refresh()}>重新加载</Button>}
      />
    );
  }

  const activeProviders = snapshot.providers.filter((item) => item.enabled).length;
  const activeAgents = snapshot.agents.filter((item) => item.status === "active").length;
  const activeTeams = snapshot.teams.filter((item) => item.status === "active").length;
  const connectedChannels = snapshot.channels.filter(
    (item) => item.status === "active" && item.connection_status === "connected",
  ).length;
  const serviceOk = snapshot.health.status === "ok";
  const qdrantOk = snapshot.knowledge.qdrant === "ok";

  return (
    <div className="overview-page">
      <section className="overview-toolbar">
        <div>
          <Text className="eyebrow">OMNIAGENT / OPERATIONS</Text>
          <Title level={3}>运行总览</Title>
          <Text type="secondary">核心资源与服务可用性</Text>
        </div>
        <div className="overview-toolbar-actions">
          {updatedAt && <Text type="secondary">更新于 {updatedAt.toLocaleTimeString()}</Text>}
          <Button icon={<RefreshCw size={16} />} loading={loading} onClick={() => void refresh()}>
            刷新
          </Button>
        </div>
      </section>

      <section className={`overview-health-banner ${serviceOk && qdrantOk ? "is-healthy" : "is-degraded"}`}>
        <div className="overview-health-icon">
          {serviceOk && qdrantOk ? <Check size={20} /> : <CircleAlert size={20} />}
        </div>
        <div className="overview-health-copy">
          <Text strong>{serviceOk && qdrantOk ? "运行状态正常" : "部分服务需要关注"}</Text>
          <Text type="secondary">
            API {serviceOk ? "可用" : "异常"} · 数据库 {snapshot.health.database === "ok" ? "可用" : "异常"} ·
            {" "}Qdrant {qdrantOk ? "可用" : "异常"}
          </Text>
        </div>
        <Tag color={serviceOk && qdrantOk ? "success" : "warning"}>
          {serviceOk && qdrantOk ? "ALL SYSTEMS OPERATIONAL" : "DEGRADED"}
        </Tag>
      </section>

      <section className="metric-grid">
        <Metric icon={<Boxes />} label="模型 Provider" value={snapshot.providers.length} detail={`${activeProviders} 个已启用`} tone="teal" />
        <Metric icon={<Bot />} label="Agent" value={snapshot.agents.length} detail={`${activeAgents} 个运行中`} tone="blue" />
        <Metric icon={<Network />} label="Team" value={snapshot.teams.length} detail={`${activeTeams} 个已启用`} tone="green" />
        <Metric icon={<Cable />} label="在线 Channel" value={connectedChannels} detail={`${snapshot.channels.length} 个已配置`} tone="cyan" />
        <Metric icon={<MessageSquareText />} label="会话" value={snapshot.chats.length} detail={`${snapshot.chats.filter((item) => item.channel !== "console").length} 个外部会话`} tone="slate" />
        <Metric icon={<BookOpen />} label="知识库" value={snapshot.knowledge.knowledge_bases} detail={`${snapshot.knowledge.publications} 份文档已发布`} tone="lime" />
      </section>

      <section className="overview-lower-grid">
        <Card className="overview-panel" title="服务状态" extra={<Activity size={17} />}>
          <StatusLine label="API 服务" detail={`${snapshot.health.name} · v${snapshot.health.version}`} ready={serviceOk} />
          <StatusLine label="数据库" detail={snapshot.health.database === "ok" ? "连接正常" : "无法连接"} ready={snapshot.health.database === "ok"} />
          <StatusLine label="向量数据库" detail={qdrantOk ? "Qdrant 可用" : "Qdrant 不可用"} ready={qdrantOk} />
        </Card>
        <Card className="overview-panel" title="资源配置" extra={<Server size={17} />}>
          <div className="resource-summary">
            <ResourceCount label="启用的 Provider" value={activeProviders} total={snapshot.providers.length} />
            <ResourceCount label="启用的 Agent" value={activeAgents} total={snapshot.agents.length} />
            <ResourceCount label="已连接的 Channel" value={connectedChannels} total={snapshot.channels.length} />
            <ResourceCount label="活动中的知识任务" value={snapshot.knowledge.active_jobs} />
          </div>
        </Card>
      </section>
    </div>
  );
}

function Metric({
  icon,
  label,
  value,
  detail,
  tone,
}: {
  icon: ReactNode;
  label: string;
  value: number;
  detail: string;
  tone: string;
}) {
  return (
    <Card className={`metric-card tone-${tone}`}>
      <div className="metric-card-top">
        <span className="metric-icon">{icon}</span>
        <Text type="secondary">{label}</Text>
      </div>
      <div className="metric-value">{value}</div>
      <Text type="secondary">{detail}</Text>
    </Card>
  );
}

function StatusLine({ label, detail, ready }: { label: string; detail: string; ready: boolean }) {
  return (
    <div className="overview-status-line">
      <span className={`status-dot ${ready ? "ready" : "error"}`} />
      <Text strong>{label}</Text>
      <Text type="secondary">{detail}</Text>
      <Tag color={ready ? "success" : "error"}>{ready ? "正常" : "异常"}</Tag>
    </div>
  );
}

function ResourceCount({ label, value, total }: { label: string; value: number; total?: number }) {
  const percent = total ? Math.min(100, Math.round((value / total) * 100)) : 0;
  return (
    <div className="resource-count">
      <div>
        <Text>{label}</Text>
        <Text strong>
          {value}
          {total !== undefined && <Text type="secondary"> / {total}</Text>}
        </Text>
      </div>
      {total !== undefined && (
        <div className="resource-track"><span style={{ width: `${percent}%` }} /></div>
      )}
    </div>
  );
}
