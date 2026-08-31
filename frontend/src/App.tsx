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
          <Text className="eyebrow">PAWTEAM LITE · STAGE 5</Text>
          <Title>让 Agent 按 Skill 思考，并在授权边界内使用 Tool。</Title>
          <Paragraph>
            本阶段加入可配置 Skill、逐 Agent Tool 权限、模型工具调用循环与持久化审计。
            模型只能请求服务端声明的能力，真正执行前还要再次通过参数和权限校验。
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
