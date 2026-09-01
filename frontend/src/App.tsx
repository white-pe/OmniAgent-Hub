import { Button, ConfigProvider, Grid, Layout, Menu, Skeleton, Tag, Typography, message } from "antd";
import {
  Activity,
  Bot,
  Boxes,
  Cable,
  LayoutDashboard,
  LogOut,
  MessageSquareText,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import zhCN from "antd/locale/zh_CN";

import { logout } from "./api/auth";
import "./styles.css";

const OverviewPage = lazy(() => import("./pages/OverviewPage"));
const ChatPage = lazy(() => import("./pages/ChatPage"));
const AgentsPage = lazy(() => import("./pages/AgentsPage"));
const TeamsPage = lazy(() => import("./pages/TeamsPage"));
const ChannelsPage = lazy(() => import("./pages/ChannelsPage"));
const ProvidersPage = lazy(() => import("./pages/ProvidersPage"));
const SystemHealth = lazy(() => import("./pages/SystemHealth"));

const { Content, Header, Sider } = Layout;
const { Text, Title } = Typography;

const pages = [
  {
    key: "overview",
    label: "系统总览",
    description: "配置状态、核心资源与运行链路",
    icon: <LayoutDashboard size={18} />,
    content: OverviewPage,
  },
  {
    key: "chat",
    label: "Agent 控制台",
    description: "跨网页与企业微信查看会话和执行审计",
    icon: <MessageSquareText size={18} />,
    content: ChatPage,
  },
  {
    key: "agents",
    label: "Agent 管理",
    description: "创建角色、编辑 Workspace、配置 Skills 与 Tools",
    icon: <Bot size={18} />,
    content: AgentsPage,
  },
  {
    key: "teams",
    label: "Team 编排",
    description: "配置协调 Agent、成员白名单与委派边界",
    icon: <Network size={18} />,
    content: TeamsPage,
  },
  {
    key: "channels",
    label: "Channel 接入",
    description: "管理企业微信机器人与外部消息通道",
    icon: <Cable size={18} />,
    content: ChannelsPage,
  },
  {
    key: "providers",
    label: "模型 Provider",
    description: "管理模型服务、加密密钥与连通性测试",
    icon: <Boxes size={18} />,
    content: ProvidersPage,
  },
  {
    key: "health",
    label: "系统状态",
    description: "检查前后端、数据库和当前版本",
    icon: <Activity size={18} />,
    content: SystemHealth,
  },
] as const;

export default function App() {
  const screens = Grid.useBreakpoint();
  const compact = screens.lg === false;
  const [collapsed, setCollapsed] = useState(compact);
  const [pageKey, setPageKey] = useState(() => {
    return window.localStorage.getItem("pawteam_active_page") ?? "overview";
  });
  const page = useMemo(
    () => pages.find((item) => item.key === pageKey) ?? pages[0],
    [pageKey],
  );
  const PageContent = page.content;

  useEffect(() => {
    if (compact) setCollapsed(true);
  }, [compact]);

  function selectPage(key: string) {
    setPageKey(key);
    window.localStorage.setItem("pawteam_active_page", key);
    if (compact) setCollapsed(true);
  }

  async function handleLogout() {
    try {
      await logout();
      window.location.reload();
    } catch (reason) {
      void message.error(reason instanceof Error ? reason.message : "退出失败");
    }
  }

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#2563eb",
          borderRadius: 6,
          colorBgLayout: "#f4f6f8",
          colorText: "#172033",
        },
        components: {
          Card: { headerBg: "transparent" },
          Menu: { itemBorderRadius: 6 },
        },
      }}
    >
      <Layout className="app-layout">
        <Sider
          className="app-sider"
          width={232}
          collapsedWidth={72}
          collapsed={collapsed}
          trigger={null}
          theme="light"
        >
          <div className="brand-block">
            <div className="brand-mark">P</div>
            {!collapsed && (
              <div>
                <Text strong className="brand-name">PawTeam Lite</Text>
                <Text type="secondary" className="brand-version">v1.0</Text>
              </div>
            )}
          </div>
          <Menu
            mode="inline"
            selectedKeys={[page.key]}
            items={pages.map(({ key, label, icon }) => ({ key, label, icon }))}
            onClick={({ key }) => selectPage(key)}
          />
          <div className="sider-footer">
            <Button
              type="text"
              icon={collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
              onClick={() => setCollapsed((value) => !value)}
            >
              {!collapsed && "收起导航"}
            </Button>
          </div>
        </Sider>

        <Layout>
          <Header className="app-header">
            <div className="page-heading">
              <Title level={4}>{page.label}</Title>
              <Text type="secondary">{page.description}</Text>
            </div>
            <div className="header-actions">
              <Tag color="success">本地运行</Tag>
              <Button icon={<LogOut size={16} />} onClick={handleLogout}>
                退出
              </Button>
            </div>
          </Header>
          <Content className="app-content">
            <Suspense fallback={<Skeleton active paragraph={{ rows: 8 }} />}>
              <PageContent />
            </Suspense>
          </Content>
        </Layout>
      </Layout>
    </ConfigProvider>
  );
}
