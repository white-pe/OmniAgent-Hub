import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Button, Card, Select, Space, Switch, Tag, Typography, message } from "antd";
import {
  Activity,
  Boxes,
  CheckCircle2,
  Clipboard,
  Clock3,
  Database,
  RefreshCw,
  Server,
  TriangleAlert,
} from "lucide-react";
import type { ReactNode } from "react";

import { listAgents, type Agent } from "../api/agents";
import { listChannels, type Channel } from "../api/channels";
import { listProviders, type Provider } from "../api/providers";
import { fetchHealth, probeHealth, type HealthResponse, type ProbeResult } from "../api/health";
import { knowledgeApi, type RagStatus } from "../api/knowledge";

const { Text, Title } = Typography;

interface HealthSnapshot {
  health: HealthResponse;
  live: ProbeResult;
  ready: ProbeResult;
  knowledge: RagStatus;
  providers: Provider[];
  agents: Agent[];
  channels: Channel[];
}

export default function SystemHealth() {
  const [snapshot, setSnapshot] = useState<HealthSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [intervalSeconds, setIntervalSeconds] = useState(30);

  const loadHealth = useCallback(async () => {
    setLoading(true);
    setError(null);
    const [healthResult, live, ready, knowledgeResult, providersResult, agentsResult, channelsResult] =
      await Promise.allSettled([
        fetchHealth(),
        probeHealth("/api/health/live"),
        probeHealth("/api/health/ready"),
        knowledgeApi.status(),
        listProviders(),
        listAgents(),
        listChannels(),
      ]);

    if (healthResult.status !== "fulfilled") {
      setError(healthResult.reason instanceof Error ? healthResult.reason.message : "健康检查接口不可用");
      setLoading(false);
      return;
    }

    const fallback = <T,>(result: PromiseSettledResult<T>, label: string): T | null => {
      if (result.status === "fulfilled") return result.value;
      console.warn(`${label} health detail unavailable`, result.reason);
      return null;
    };
    const knowledge = fallback(knowledgeResult, "Qdrant") ?? {
      qdrant: "unavailable",
      documents: 0,
      knowledge_bases: 0,
      publications: 0,
      active_jobs: 0,
    };
    const providers = fallback(providersResult, "Provider") ?? [];
    const agents = fallback(agentsResult, "Agent") ?? [];
    const channels = fallback(channelsResult, "Channel") ?? [];
    const detailFailed = [knowledgeResult, providersResult, agentsResult, channelsResult]
      .some((result) => result.status === "rejected");

    setSnapshot({
      health: healthResult.value,
      live: live.status === "fulfilled" ? live.value : { ok: false, status: null, latencyMs: 0 },
      ready: ready.status === "fulfilled" ? ready.value : { ok: false, status: null, latencyMs: 0 },
      knowledge,
      providers,
      agents,
      channels,
    });
    if (detailFailed) setError("部分服务详情暂不可用，已用默认值显示；请检查相关 API 与服务连接。");
    setCheckedAt(new Date());
    setLoading(false);
  }, []);

  useEffect(() => {
    void loadHealth();
  }, [loadHealth]);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = window.setInterval(() => void loadHealth(), intervalSeconds * 1000);
    return () => window.clearInterval(timer);
  }, [autoRefresh, intervalSeconds, loadHealth]);

  const summary = useMemo(() => {
    if (!snapshot) return "";
    return [
      `OmniAgent ${snapshot.health.version}`,
      `环境: ${snapshot.health.environment}`,
      `API: ${snapshot.health.status}`,
      `数据库: ${snapshot.health.database}`,
      `Liveness: ${probeLabel(snapshot.live)}`,
      `Readiness: ${probeLabel(snapshot.ready)}`,
      `Qdrant: ${snapshot.knowledge.qdrant}`,
      `Provider: ${snapshot.providers.filter((item) => item.enabled).length}/${snapshot.providers.length} enabled`,
      `Agent: ${snapshot.agents.filter((item) => item.status === "active").length}/${snapshot.agents.length} active`,
      `Channel: ${snapshot.channels.filter((item) => item.connection_status === "connected").length}/${snapshot.channels.length} connected`,
      `检查时间: ${checkedAt?.toLocaleString() ?? "unknown"}`,
    ].join("\n");
  }, [snapshot, checkedAt]);

  async function copySummary() {
    try {
      await navigator.clipboard.writeText(summary);
      void message.success("诊断摘要已复制");
    } catch {
      void message.error("复制失败，请检查浏览器剪贴板权限");
    }
  }

  const systemOk = snapshot?.health.status === "ok"
    && snapshot.knowledge.qdrant === "ok"
    && snapshot.live.ok
    && snapshot.ready.ok;

  return (
    <div className="health-page">
      <section className="health-toolbar">
        <div>
          <Text className="eyebrow">OPERATIONS / HEALTH</Text>
          <Title level={3}>系统状态</Title>
          <Text type="secondary">服务探测、依赖可用性与配置概况</Text>
        </div>
        <Space wrap>
          <Text type="secondary">自动刷新</Text>
          <Switch checked={autoRefresh} onChange={setAutoRefresh} aria-label="自动刷新" />
          <Select
            aria-label="刷新间隔"
            value={intervalSeconds}
            onChange={setIntervalSeconds}
            options={[
              { value: 15, label: "15 秒" },
              { value: 30, label: "30 秒" },
              { value: 60, label: "60 秒" },
            ]}
            style={{ width: 104 }}
            disabled={!autoRefresh}
          />
          {snapshot && (
            <Button icon={<Clipboard size={16} />} onClick={() => void copySummary()}>
              复制诊断
            </Button>
          )}
          <Button type="primary" icon={<RefreshCw size={16} />} loading={loading} onClick={() => void loadHealth()}>
            立即检查
          </Button>
        </Space>
      </section>

      {error && <Alert showIcon type={snapshot ? "warning" : "error"} message={error} />}

      {loading && !snapshot ? (
        <Card loading />
      ) : snapshot ? (
        <>
          <section className={`health-hero ${systemOk ? "is-healthy" : "is-degraded"}`}>
            <div className="health-hero-icon">
              {systemOk ? <CheckCircle2 size={25} /> : <TriangleAlert size={25} />}
            </div>
            <div className="health-hero-copy">
              <Title level={4}>{systemOk ? "所有关键依赖正常" : "检测到需要关注的状态"}</Title>
              <Text type="secondary">
                {snapshot.health.name} · {snapshot.health.environment} · v{snapshot.health.version}
              </Text>
            </div>
            <div className="health-checked">
              <Clock3 size={15} />
              <Text type="secondary">{checkedAt?.toLocaleString() ?? "尚未完成检查"}</Text>
            </div>
          </section>

          <section className="health-check-grid">
            <ProbeCard icon={<Activity />} label="API 存活探测" detail="进程是否能响应请求" result={snapshot.live} />
            <ProbeCard icon={<Server />} label="API 就绪探测" detail="是否满足接收业务流量条件" result={snapshot.ready} />
            <DependencyCard
              icon={<Database />}
              label="数据库"
              detail="应用数据与任务状态"
              ok={snapshot.health.database === "ok"}
              value={snapshot.health.database}
            />
            <DependencyCard
              icon={<Boxes />}
              label="Qdrant"
              detail={`${snapshot.knowledge.publications} 份文档已发布`}
              ok={snapshot.knowledge.qdrant === "ok"}
              value={snapshot.knowledge.qdrant}
            />
          </section>

          <section className="health-detail-grid">
            <Card className="health-detail-card" title="运行配置" extra={<Server size={17} />}>
              <DetailRow label="运行环境" value={snapshot.health.environment} neutral />
              <DetailRow label="应用版本" value={`v${snapshot.health.version}`} neutral />
              <DetailRow label="活动知识任务" value={`${snapshot.knowledge.active_jobs}`} neutral />
              <DetailRow label="知识库 / 已发布文档" value={`${snapshot.knowledge.knowledge_bases} / ${snapshot.knowledge.publications}`} neutral />
            </Card>
            <Card className="health-detail-card" title="业务资源连接" extra={<Activity size={17} />}>
              <DetailRow
                label="模型 Provider"
                value={`${snapshot.providers.filter((item) => item.enabled).length} / ${snapshot.providers.length} 已启用`}
                ok={snapshot.providers.some((item) => item.enabled)}
                emptyLabel="尚未配置可用 Provider"
              />
              <DetailRow
                label="Agent"
                value={`${snapshot.agents.filter((item) => item.status === "active").length} / ${snapshot.agents.length} 运行中`}
                ok={snapshot.agents.some((item) => item.status === "active")}
                emptyLabel="尚未启用 Agent"
              />
              <DetailRow
                label="Channel"
                value={`${snapshot.channels.filter((item) => item.connection_status === "connected").length} / ${snapshot.channels.length} 已连接`}
                ok={snapshot.channels.length === 0 || snapshot.channels.some((item) => item.connection_status === "connected")}
                emptyLabel="无外部 Channel"
              />
            </Card>
          </section>
        </>
      ) : (
        <Card className="health-empty">
          <Text type="secondary">没有可显示的状态数据。</Text>
        </Card>
      )}
    </div>
  );
}

function ProbeCard({
  icon,
  label,
  detail,
  result,
}: {
  icon: ReactNode;
  label: string;
  detail: string;
  result: ProbeResult;
}) {
  return (
    <Card className="health-check-card">
      <div className="health-check-top">
        <span className="health-check-icon">{icon}</span>
        <Tag color={result.ok ? "success" : "error"}>{result.ok ? "正常" : "异常"}</Tag>
      </div>
      <Text strong>{label}</Text>
      <Text type="secondary">{detail}</Text>
      <div className="probe-meta">
        <Text type="secondary">HTTP {result.status ?? "无响应"}</Text>
        <Text type="secondary">{result.latencyMs} ms</Text>
      </div>
    </Card>
  );
}

function DependencyCard({
  icon,
  label,
  detail,
  ok,
  value,
}: {
  icon: ReactNode;
  label: string;
  detail: string;
  ok: boolean;
  value: string;
}) {
  return (
    <Card className="health-check-card">
      <div className="health-check-top">
        <span className="health-check-icon">{icon}</span>
        <Tag color={ok ? "success" : "error"}>{ok ? "正常" : "异常"}</Tag>
      </div>
      <Text strong>{label}</Text>
      <Text type="secondary">{detail}</Text>
      <div className="probe-meta"><Text type="secondary">{value}</Text></div>
    </Card>
  );
}

function DetailRow({
  label,
  value,
  ok,
  neutral = false,
  emptyLabel,
}: {
  label: string;
  value: string;
  ok?: boolean;
  neutral?: boolean;
  emptyLabel?: string;
}) {
  const statusOk = ok ?? false;
  return (
    <div className="health-detail-row">
      <Text>{label}</Text>
      <Space size={8}>
        {emptyLabel && value.startsWith("0 /") ? (
          <Text type="secondary">{emptyLabel}</Text>
        ) : neutral ? (
          <Tag color="cyan">{value}</Tag>
        ) : (
          <>
            <span className={`status-dot ${statusOk ? "ready" : "error"}`} />
            <Text type={statusOk ? undefined : "secondary"}>{value}</Text>
          </>
        )}
      </Space>
    </div>
  );
}

function probeLabel(result: ProbeResult): string {
  return result.status === null ? "unavailable" : `${result.ok ? "ok" : "failed"} (HTTP ${result.status}, ${result.latencyMs}ms)`;
}
