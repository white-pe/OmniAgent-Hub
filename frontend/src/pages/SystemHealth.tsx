import { useEffect, useState } from "react";
import { Button, Card, Space, Spin, Tag, Typography } from "antd";

import { fetchHealth, type HealthResponse } from "../api/health";

const { Paragraph, Text } = Typography;

export default function SystemHealth() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const loadHealth = async () => {
    setLoading(true);
    setError(null);
    try {
      setHealth(await fetchHealth());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "未知错误");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadHealth();
  }, []);

  return (
    <Space direction="vertical" size="large" className="full-width">
      <Card className="status-card" title="系统健康状态">
        {loading ? (
          <Spin tip="正在检查后端与数据库" />
        ) : error ? (
          <Space direction="vertical">
            <Tag color="error">连接失败</Tag>
            <Text type="danger">{error}</Text>
            <Button onClick={() => void loadHealth()}>重新检查</Button>
          </Space>
        ) : (
          <div className="status-grid">
            <Status label="服务" value={health?.status ?? "degraded"} />
            <Status label="数据库" value={health?.database ?? "unavailable"} />
            <Status label="环境" value={health?.environment ?? "unknown"} neutral />
            <Status label="版本" value={health?.version ?? "unknown"} neutral />
          </div>
        )}
      </Card>
      <section className="flow">
        <Text strong>阶段 0 请求链路</Text>
        <Paragraph>
          React → Vite Proxy → FastAPI Router → SQLAlchemy AsyncEngine → SQLite
        </Paragraph>
      </section>
    </Space>
  );
}

function Status({
  label,
  value,
  neutral = false,
}: {
  label: string;
  value: string;
  neutral?: boolean;
}) {
  const healthy = value === "ok";
  return (
    <div className="status-item">
      <Text type="secondary">{label}</Text>
      <Tag color={neutral ? "blue" : healthy ? "success" : "error"}>{value}</Tag>
    </div>
  );
}
