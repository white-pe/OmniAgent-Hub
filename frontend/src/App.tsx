import { Button, ConfigProvider, Tabs, Typography, message } from "antd";
import zhCN from "antd/locale/zh_CN";

import AgentsPage from "./pages/AgentsPage";
import ChatPage from "./pages/ChatPage";
import ChannelsPage from "./pages/ChannelsPage";
import ProvidersPage from "./pages/ProvidersPage";
import SystemHealth from "./pages/SystemHealth";
import TeamsPage from "./pages/TeamsPage";
import { logout } from "./api/auth";
import "./styles.css";

const { Paragraph, Text, Title } = Typography;

export default function App() {
  async function handleLogout() {
    try {
      await logout();
      window.location.reload();
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : "退出失败");
    }
  }

  return (
    <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: "#ff7a1a" } }}>
      <main className="shell">
        <section className="hero hero-production">
          <div>
            <Text className="eyebrow">PAWTEAM LITE · 1.0 PRODUCTION</Text>
            <Title>一个会话内核，安全连接网页与企业微信。</Title>
            <Paragraph>
              网页和企业微信共享同一套 Chat、Run 与消息历史；统一控制台可以查看所有入口的会话，
              并保留清晰的来源、权限和执行审计边界。
            </Paragraph>
          </div>
          <Button onClick={handleLogout}>退出登录</Button>
        </section>
        <Tabs
          defaultActiveKey="chat"
          size="large"
          items={[
            { key: "chat", label: "Agent 控制台", children: <ChatPage /> },
            { key: "agents", label: "Blueprint 与 Agent", children: <AgentsPage /> },
            { key: "teams", label: "Team 与委派", children: <TeamsPage /> },
            { key: "channels", label: "企业微信 Channel", children: <ChannelsPage /> },
            { key: "providers", label: "Provider 与模型", children: <ProvidersPage /> },
            { key: "health", label: "系统地基", children: <SystemHealth /> },
          ]}
        />
      </main>
    </ConfigProvider>
  );
}
