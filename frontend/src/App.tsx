import { ConfigProvider, Tabs, Typography } from "antd";
import zhCN from "antd/locale/zh_CN";

import ProvidersPage from "./pages/ProvidersPage";
import SystemHealth from "./pages/SystemHealth";
import "./styles.css";

const { Paragraph, Text, Title } = Typography;

export default function App() {
  return (
    <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: "#ff7a1a" } }}>
      <main className="shell">
        <section className="hero">
          <Text className="eyebrow">PAWTEAM LITE · STAGE 1</Text>
          <Title>先可靠地调用一个模型，再把它交给 Agent。</Title>
          <Paragraph>
            本阶段实现 Provider、独立模型配置、加密密钥管理和 SSE 流式调用。
            Agent、Skill 与 Channel 仍会在后续阶段逐层加入。
          </Paragraph>
        </section>
        <Tabs
          defaultActiveKey="providers"
          size="large"
          items={[
            { key: "providers", label: "Provider 与模型", children: <ProvidersPage /> },
            { key: "health", label: "系统地基", children: <SystemHealth /> },
          ]}
        />
      </main>
    </ConfigProvider>
  );
}
