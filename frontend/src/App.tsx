import { ConfigProvider, Tabs, Typography } from "antd";
import zhCN from "antd/locale/zh_CN";

import AgentsPage from "./pages/AgentsPage";
import ChatPage from "./pages/ChatPage";
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
          <Text className="eyebrow">PAWTEAM LITE · STAGE 6</Text>
          <Title>让多个 Agent 在清晰边界内组成一支可审计的 Team。</Title>
          <Paragraph>
            协调 Agent 可以把边界清晰的任务交给 Team 成员；每次委派都会创建独立子 Run，
            保留成员自己的身份、模型、Workspace、Skills 与 Tools。
          </Paragraph>
        </section>
        <Tabs
          defaultActiveKey="chat"
          size="large"
          items={[
            { key: "chat", label: "Agent 控制台", children: <ChatPage /> },
            { key: "agents", label: "Blueprint 与 Agent", children: <AgentsPage /> },
            { key: "teams", label: "Team 与委派", children: <TeamsPage /> },
            { key: "providers", label: "Provider 与模型", children: <ProvidersPage /> },
            { key: "health", label: "系统地基", children: <SystemHealth /> },
          ]}
        />
      </main>
    </ConfigProvider>
  );
}
