import { ConfigProvider, Tabs, Typography } from "antd";
import zhCN from "antd/locale/zh_CN";

import AgentsPage from "./pages/AgentsPage";
import ProvidersPage from "./pages/ProvidersPage";
import SystemHealth from "./pages/SystemHealth";
import "./styles.css";

const { Paragraph, Text, Title } = Typography;

export default function App() {
  return (
    <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: "#ff7a1a" } }}>
      <main className="shell">
        <section className="hero">
          <Text className="eyebrow">PAWTEAM LITE · STAGE 2</Text>
          <Title>让每个 Agent 都拥有清晰的身份与独立 Workspace。</Title>
          <Paragraph>
            本阶段实现 Agent 元数据、Provider/Model 绑定、独立 Markdown Workspace
            与配置版本控制。自然语言 Blueprint、Skill 和 Channel 将继续加入。
          </Paragraph>
        </section>
        <Tabs
          defaultActiveKey="agents"
          size="large"
          items={[
            { key: "agents", label: "Agent 与 Workspace", children: <AgentsPage /> },
            { key: "providers", label: "Provider 与模型", children: <ProvidersPage /> },
            { key: "health", label: "系统地基", children: <SystemHealth /> },
          ]}
        />
      </main>
    </ConfigProvider>
  );
}
