import type { ReactNode } from "react";
import { Alert, Button, Card, Skeleton, Tag, Typography, message } from "antd";
import {
  Bot,
  Boxes,
  Cable,
  CheckCircle2,
  MessageSquareText,
  Network,
  RefreshCw,
} from "lucide-react";
import { useEffect, useState } from "react";

import { listAgents, type Agent } from "../api/agents";
import { listChannels, type Channel } from "../api/channels";
import { listChats, type ChatSession } from "../api/chats";
import { fetchHealth, type HealthResponse } from "../api/health";
import { listProviders, type Provider } from "../api/providers";
import { listTeams, type Team } from "../api/teams";

const { Paragraph, Text, Title } = Typography;

interface Snapshot {
  agents: Agent[];
  channels: Channel[];
  chats: ChatSession[];
  health: HealthResponse;
  providers: Provider[];
  teams: Team[];
}

export default function OverviewPage() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    try {
      const [agents, channels, chats, health, providers, teams] = await Promise.all([
        listAgents(),
        listChannels(),
        listChats(),
        fetchHealth(),
        listProviders(),
        listTeams(),
      ]);
      setSnapshot({ agents, channels, chats, health, providers, teams });
    } catch (reason) {
      void message.error(reason instanceof Error ? reason.message : "总览数据加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  if (!snapshot && loading) {
    return <Skeleton active paragraph={{ rows: 8 }} />;
  }
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
  const activeChannels = snapshot.channels.filter((item) => item.status === "active").length;
  const connectedChannels = snapshot.channels.filter(
    (item) => item.connection_status === "connected",
  ).length;

  return (
    <div className="overview-page">
      <section className="overview-toolbar">
        <div>
          <Title level={3}>项目运行总览</Title>
          <Paragraph type="secondary">
            从模型接入到多 Agent 协作，再到跨 Channel 会话，所有核心资源都汇总在这里。
          </Paragraph>
        </div>
        <Button icon={<RefreshCw size={16} />} loading={loading} onClick={() => void refresh()}>
          刷新状态
        </Button>
      </section>

      <section className="metric-grid">
        <Metric icon={<Boxes />} label="Provider" value={snapshot.providers.length} detail={`${activeProviders} 个已启用`} />
        <Metric icon={<Bot />} label="Agent" value={snapshot.agents.length} detail={`${activeAgents} 个运行中`} />
        <Metric icon={<Network />} label="Team" value={snapshot.teams.length} detail={`${activeTeams} 个可委派`} />
        <Metric icon={<Cable />} label="Channel" value={snapshot.channels.length} detail={`${connectedChannels} 个已连接`} />
        <Metric icon={<MessageSquareText />} label="会话" value={snapshot.chats.length} detail={`${snapshot.chats.filter((item) => item.channel !== "console").length} 个来自外部`} />
      </section>

      <section className="overview-grid">
        <div className="overview-section">
          <div className="section-heading">
            <Title level={5}>核心业务链路</Title>
            <Text type="secondary">创建和运行 Agent 时，资源按下面的顺序组合</Text>
          </div>
          <div className="architecture-flow">
            <FlowNode title="Provider" detail="模型协议与加密密钥" ready={activeProviders > 0} />
            <span className="flow-arrow">→</span>
            <FlowNode title="Agent" detail="角色、Workspace 与能力" ready={activeAgents > 0} />
            <span className="flow-arrow">→</span>
            <FlowNode title="Team / Channel" detail="协作编排与消息入口" ready={activeTeams + activeChannels > 0} />
            <span className="flow-arrow">→</span>
            <FlowNode title="Chat / Run" detail="会话、执行与完整审计" ready={snapshot.chats.length > 0} />
          </div>
        </div>

        <div className="overview-section readiness-panel">
          <div className="section-heading">
            <Title level={5}>当前可用性</Title>
            <Tag color={snapshot.health.status === "ok" ? "success" : "error"}>
              {snapshot.health.status === "ok" ? "系统正常" : "系统降级"}
            </Tag>
          </div>
          <Readiness label="数据库" ready={snapshot.health.database === "ok"} detail={snapshot.health.database} />
          <Readiness label="模型调用" ready={activeProviders > 0} detail={activeProviders ? `${activeProviders} 个 Provider 可用` : "尚未配置"} />
          <Readiness label="Agent 对话" ready={activeAgents > 0} detail={activeAgents ? `${activeAgents} 个 Agent 已启用` : "尚未创建"} />
          <Readiness label="团队委派" ready={activeTeams > 0} detail={activeTeams ? `${activeTeams} 个 Team 可用` : "可选能力"} optional />
          <Readiness label="外部 Channel" ready={connectedChannels > 0} detail={connectedChannels ? `${connectedChannels} 个长连接在线` : "可选能力"} optional />
        </div>
      </section>
    </div>
  );
}

function Metric({ icon, label, value, detail }: { icon: ReactNode; label: string; value: number; detail: string }) {
  return (
    <Card className="metric-card">
      <div className="metric-icon">{icon}</div>
      <div>
        <Text type="secondary">{label}</Text>
        <div className="metric-value">{value}</div>
        <Text type="secondary">{detail}</Text>
      </div>
    </Card>
  );
}

function FlowNode({ title, detail, ready }: { title: string; detail: string; ready: boolean }) {
  return (
    <div className={ready ? "flow-node ready" : "flow-node"}>
      <CheckCircle2 size={18} />
      <Text strong>{title}</Text>
      <Text type="secondary">{detail}</Text>
    </div>
  );
}

function Readiness({ label, ready, detail, optional = false }: { label: string; ready: boolean; detail: string; optional?: boolean }) {
  return (
    <div className="readiness-row">
      <div>
        <Text strong>{label}</Text>
        {optional && <Tag>可选</Tag>}
      </div>
      <div>
        <span className={ready ? "status-dot ready" : "status-dot"} />
        <Text type="secondary">{detail}</Text>
      </div>
    </div>
  );
}
