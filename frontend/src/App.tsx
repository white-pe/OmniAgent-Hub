import { ConfigProvider, Tabs, Typography } from "antd";
import zhCN from "antd/locale/zh_CN";

import AgentsPage from "./pages/AgentsPage";
import ChatPage from "./pages/ChatPage";
import ProvidersPage from "./pages/ProvidersPage";
import SystemHealth from "./pages/SystemHealth";
import "./styles.css";

const { Paragraph, Text, Title } = Typography;

export default function App() {
  return (
    <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: "#ff7a1a" } }}>
      <main className="shell">
        <section className="hero">
          <Text className="eyebrow">PAWTEAM LITE · STAGE 4</Text>
          <Title>让 Agent 带着自己的身份，在可恢复的会话中真正工作。</Title>
          <Paragraph>
            本阶段加入 Session、Message、Run、PromptBuilder 和可重放 SSE。
            每次回答都有状态、历史与停止边界，刷新页面后仍能继续查看。
          </Paragraph>
        </section>
        <Tabs
          defaultActiveKey="chat"
          size="large"
          items={[
            { key: "chat", label: "Agent 控制台", children: <ChatPage /> },
            { key: "agents", label: "Blueprint 与 Agent", children: <AgentsPage /> },
            { key: "providers", label: "Provider 与模型", children: <ProvidersPage /> },
            { key: "health", label: "系统地基", children: <SystemHealth /> },
          ]}
        />
      </main>
    </ConfigProvider>
  );
}
