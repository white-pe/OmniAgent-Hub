import { Alert, Button, Card, Form, Input, Spin, Typography, message } from "antd";
import { type ReactNode, useCallback, useEffect, useState } from "react";

import { getAuthStatus, login } from "../api/auth";
import { UNAUTHORIZED_EVENT } from "../api/http";

const { Paragraph, Text, Title } = Typography;

interface Props {
  children: ReactNode;
}

export default function AuthGate({ children }: Props) {
  const [loading, setLoading] = useState(true);
  const [authenticated, setAuthenticated] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const status = await getAuthStatus();
      setAuthenticated(status.authenticated);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法连接后端服务");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const unauthorized = () => setAuthenticated(false);
    window.addEventListener(UNAUTHORIZED_EVENT, unauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, unauthorized);
  }, [refresh]);

  async function submit(values: { password: string }) {
    setSubmitting(true);
    try {
      await login(values.password);
      setAuthenticated(true);
      setError(null);
      message.success("登录成功");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "登录失败");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return <div className="auth-loading"><Spin size="large" /></div>;
  }
  if (authenticated) return children;

  return (
    <main className="auth-shell">
      <Card className="auth-card">
        <Text className="eyebrow">PAWTEAM LITE · PRIVATE CONSOLE</Text>
        <Title level={2}>管理员登录</Title>
        <Paragraph type="secondary">
          Provider 密钥、Agent 工作区和企业微信凭证都属于私有数据，请使用部署时设置的管理员密码。
        </Paragraph>
        {error && <Alert type="error" showIcon title={error} />}
        <Form layout="vertical" onFinish={submit} requiredMark={false}>
          <Form.Item
            label="管理员密码"
            name="password"
            rules={[{ required: true, message: "请输入管理员密码" }]}
          >
            <Input.Password
              autoFocus
              autoComplete="current-password"
              prefix="🔒"
              placeholder="PAWTEAM_ADMIN_PASSWORD"
            />
          </Form.Item>
          <Button block type="primary" htmlType="submit" loading={submitting}>
            进入控制台
          </Button>
        </Form>
      </Card>
    </main>
  );
}
