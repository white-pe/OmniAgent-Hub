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
          <Text className="eyebrow">PAWTEAM LITE · STAGE 7</Text>
          <Title>让企业微信成为 Agent 的一个真实入口。</Title>
          <Paragraph>
            企业微信消息经过验签与 AES 解密后映射到内部会话；Agent 或 Team 在后台完成任务，
            再通过企业微信应用消息主动回复，全程保留可审计记录。
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
