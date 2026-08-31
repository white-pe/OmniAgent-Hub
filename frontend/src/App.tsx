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
          <Text className="eyebrow">PAWTEAM LITE · STAGE 3</Text>
          <Title>先审查 Blueprint，再把自然语言变成专用 Agent。</Title>
          <Paragraph>
            本阶段把模型输出限制为严格 Schema 草案，并通过预览、编辑、白名单校验和
            明确确认，安全地生成 Agent 元数据与独立 Markdown Workspace。
          </Paragraph>
        </section>
        <Tabs
          defaultActiveKey="agents"
          size="large"
          items={[
            { key: "agents", label: "Blueprint 与 Agent", children: <AgentsPage /> },
            { key: "providers", label: "Provider 与模型", children: <ProvidersPage /> },
            { key: "health", label: "系统地基", children: <SystemHealth /> },
          ]}
        />
      </main>
    </ConfigProvider>
  );
}
