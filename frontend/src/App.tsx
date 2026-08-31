import { ConfigProvider, Tabs, Typography } from "antd";
import zhCN from "antd/locale/zh_CN";

import AgentsPage from "./pages/AgentsPage";
import ChatPage from "./pages/ChatPage";
import ChannelsPage from "./pages/ChannelsPage";
import ProvidersPage from "./pages/ProvidersPage";
import SystemHealth from "./pages/SystemHealth";
import TeamsPage from "./pages/TeamsPage";
import "./styles.css";

const { Paragraph, Text, Title } = Typography;

export default function App() {
  return (
    <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: "#ff7a1a" } }}>
      <main className="shell">
        <section className="hero">
          <Text className="eyebrow">PAWTEAM LITE · STAGE 7.1</Text>
          <Title>扫码，让企业微信成为 Agent 的真实入口。</Title>
          <Paragraph>
            智能机器人通过 WebSocket 长连接收发消息，无需公网回调；传统自建应用模式继续保留。
            两种入口都复用同一套 Agent、Team、Run 与消息审计链路。
          </Paragraph>
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
