import { useEffect, useState, type ReactNode } from "react";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Select,
  Segmented,
  Space,
  Switch,
  Tabs,
  Tag,
  Typography,
  message,
} from "antd";

import {
  Activity,
  Bot,
  Cpu,
  FolderKanban,
  Plus,
  Sparkles,
} from "lucide-react";

import {
  createAgent,
  deleteAgent,
  getWorkspaceFile,
  listAgents,
  toggleAgent,
  updateAgent,
  updateWorkspaceFile,
  type Agent,
  type AgentCreateInput,
  type WorkspaceFile,
  type WorkspaceFilename,
} from "../api/agents";
import { listProviders, type Provider } from "../api/providers";
import BlueprintCreator from "../components/BlueprintCreator";
import AgentCapabilities from "../components/AgentCapabilities";

const { Paragraph, Text } = Typography;
const { TextArea } = Input;
const WORKSPACE_FILES: WorkspaceFilename[] = [
  "AGENTS.md",
  "SOUL.md",
  "PROFILE.md",
  "MEMORY.md",
];

type AgentFormValues = AgentCreateInput;

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState<Agent | null>(null);
  const [workspaceAgent, setWorkspaceAgent] = useState<Agent | null>(null);
  const [capabilityAgent, setCapabilityAgent] = useState<Agent | null>(null);
  const [workspaceFile, setWorkspaceFile] = useState<WorkspaceFile | null>(null);
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const [workspaceSaving, setWorkspaceSaving] = useState(false);
  const [creationMode, setCreationMode] = useState<"blueprint" | "manual">("blueprint");
  const [activeFilename, setActiveFilename] =
    useState<WorkspaceFilename>("AGENTS.md");
  const [createForm] = Form.useForm<AgentFormValues>();
  const [editForm] = Form.useForm<AgentFormValues>();
  const createProviderId = Form.useWatch("provider_id", createForm);
  const editProviderId = Form.useWatch("provider_id", editForm);

  const enabledProviders = providers.filter((provider) => provider.enabled);
  const createModels = modelsFor(enabledProviders, createProviderId);
  const editModels = modelsFor(enabledProviders, editProviderId);

  const refresh = async () => {
    setLoading(true);
    try {
      const [nextAgents, nextProviders] = await Promise.all([
        listAgents(),
        listProviders(),
      ]);
      setAgents(nextAgents);
      setProviders(nextProviders);
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const create = async (values: AgentFormValues) => {
    setSaving(true);
    try {
      await createAgent(values);
      createForm.resetFields();
      void message.success("Agent 与独立 Workspace 已创建");
      await refresh();
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setSaving(false);
    }
  };

  const openEditor = (agent: Agent) => {
    setEditing(agent);
    editForm.setFieldsValue({
      name: agent.name,
      description: agent.description,
      provider_id: agent.provider_id,
      model_id: agent.model_id,
      is_coordinator: agent.is_coordinator,
    });
  };

  const saveEdit = async (values: AgentFormValues) => {
    if (!editing) return;
    setSaving(true);
    try {
      await updateAgent(editing.id, {
        expected_version: editing.version,
        ...values,
      });
      setEditing(null);
      void message.success("Agent 元数据已更新");
      await refresh();
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setSaving(false);
    }
  };

  const changeStatus = async (agent: Agent) => {
    try {
      await toggleAgent(agent.id);
      await refresh();
    } catch (reason) {
      void message.error(errorText(reason));
    }
  };

  const remove = async (agent: Agent) => {
    try {
      await deleteAgent(agent.id);
      void message.success("Agent 元数据和 Workspace 已删除");
      await refresh();
    } catch (reason) {
      void message.error(errorText(reason));
    }
  };

  const loadWorkspaceFile = async (
    agent: Agent,
    filename: WorkspaceFilename,
  ) => {
    setWorkspaceLoading(true);
    setActiveFilename(filename);
    try {
      setWorkspaceFile(await getWorkspaceFile(agent.id, filename));
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setWorkspaceLoading(false);
    }
  };

  const openWorkspace = (agent: Agent) => {
    setWorkspaceAgent(agent);
    setWorkspaceFile(null);
    void loadWorkspaceFile(agent, "AGENTS.md");
  };

  const saveWorkspace = async () => {
    if (!workspaceAgent || !workspaceFile) return;
    setWorkspaceSaving(true);
    try {
      const saved = await updateWorkspaceFile(
        workspaceAgent.id,
        activeFilename,
        workspaceFile.content,
        workspaceFile.agent_version,
      );
      setWorkspaceFile(saved);
      void message.success(`${activeFilename} 已原子保存`);
      await refresh();
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setWorkspaceSaving(false);
    }
  };

  return (
    <div className="agent-layout">
      <section className="agent-page-heading">
        <div>
          <Text className="eyebrow">AGENT STUDIO / CONFIGURATION</Text>
          <Typography.Title level={3}>Agent 管理</Typography.Title>
          <Text type="secondary">创建专属角色，绑定模型，并管理独立工作空间与运行能力。</Text>
        </div>
        <div className="agent-overview-counts">
          <ResourceBadge icon={<Bot />} label="Agent" value={agents.length} />
          <ResourceBadge icon={<Activity />} label="运行中" value={agents.filter((agent) => agent.status === "active").length} />
          <ResourceBadge icon={<Cpu />} label="可用模型" value={enabledProviders.reduce((count, provider) => count + provider.models.filter((model) => model.enabled).length, 0)} />
        </div>
      </section>

      {!enabledProviders.length && (
        <Alert
          type="warning"
          showIcon
          title="创建 Agent 前，需要至少一个已启用的 Provider 和 Model。"
        />
      )}

      <section className="agent-creation-section">
        <div className="section-title-row">
          <div>
            <Typography.Title level={4}>创建 Agent</Typography.Title>
            <Text type="secondary">选择创建流程。AI 创建会先生成完整角色草案；手动创建仅建立基础 Agent。</Text>
          </div>
          <Segmented
            value={creationMode}
            onChange={(value) => setCreationMode(value as "blueprint" | "manual")}
            options={[
              {
                value: "blueprint",
                label: <span className="agent-mode-option"><Sparkles size={15} /> AI 生成角色蓝图</span>,
              },
              {
                value: "manual",
                label: <span className="agent-mode-option"><Plus size={15} /> 手动创建空白 Agent</span>,
              },
            ]}
          />
        </div>
        <div className="agent-creation-workspace">
          {creationMode === "blueprint" ? (
            <div className="agent-blueprint-workspace">
              <div className="agent-mode-summary">
                <span className="creation-path-icon"><Sparkles size={18} /></span>
                <div>
                  <Text strong>从职责描述生成专用角色</Text>
                  <Text type="secondary">
                    AI 会生成身份、目标、规则和能力请求。你可以在确认前编辑草案；此流程需要可用的聊天模型。
                  </Text>
                </div>
                <Tag color="cyan">生成后审核</Tag>
              </div>
            <BlueprintCreator providers={enabledProviders} onCreated={refresh} />
            </div>
          ) : (
            <div className="agent-manual-workspace">
              <div className="agent-mode-summary">
                <span className="creation-path-icon manual"><Plus size={18} /></span>
                <div>
                  <Text strong>创建空白 Agent</Text>
                  <Text type="secondary">
                    只设置名称、用途和运行模型，不生成角色指令。创建后再编辑 Workspace、Skills 与 Tools。
                  </Text>
                </div>
                <Tag>基础配置</Tag>
              </div>
              <div className="agent-form-card">
              <AgentForm
                form={createForm}
                providers={enabledProviders}
                models={createModels}
                onProviderChange={() => createForm.setFieldValue("model_id", undefined)}
                onFinish={create}
                saving={saving}
                submitText="创建 Agent 与 Workspace"
              />
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="agent-list-section">
      <div className="section-title-row">
        <div>
          <Typography.Title level={4}>已创建的 Agent</Typography.Title>
          <Text type="secondary">模型绑定、Workspace 与运行能力</Text>
        </div>
        <Tag>{agents.length} 个</Tag>
      </div>
      <div className="agent-list-shell">
        {loading && <Card loading />}
        {!agents.length && !loading ? (
          <Empty description="还没有 Agent" />
        ) : (
          <List
            grid={{ gutter: 16, xs: 1, md: 2 }}
            dataSource={agents}
            renderItem={(agent) => (
              <List.Item>
                <Card
                  className="agent-card"
                  title={
                    <div className="agent-card-title">
                      <span className="agent-avatar"><Bot size={18} /></span>
                      <div>
                        <Text strong>{agent.name}</Text>
                        <Space size={6} wrap>
                          <Tag color={agent.status === "active" ? "success" : "default"}>
                            {agent.status === "active" ? "运行中" : "已停用"}
                          </Tag>
                          {agent.is_coordinator && <Tag color="cyan">协调 Agent</Tag>}
                        </Space>
                      </div>
                    </div>
                  }
                  extra={
                    <Switch
                      checked={agent.status === "active"}
                      onChange={() => void changeStatus(agent)}
                    />
                  }
                >
                  <Paragraph className="agent-card-description">{agent.description || "暂无用途说明"}</Paragraph>
                  <div className="agent-meta">
                    <Text type="secondary"><Cpu size={14} /> 模型</Text>
                    <Text>{agent.provider_name} / {agent.model_name}</Text>
                    <Text type="secondary"><FolderKanban size={14} /> Workspace</Text>
                    <Text code copyable>{agent.workspace_path}</Text>
                    <Text type="secondary">配置版本</Text>
                    <Text>v{agent.version}</Text>
                  </div>
                  <div className="agent-actions">
                    <Button onClick={() => setCapabilityAgent(agent)}>
                      配置 Skills / Tools
                    </Button>
                    <Button type="primary" onClick={() => openWorkspace(agent)}>
                      编辑 Workspace
                    </Button>
                    <Button onClick={() => openEditor(agent)}>编辑元数据</Button>
                    <Popconfirm
                      title="确定删除 Agent 及其整个 Workspace？"
                      onConfirm={() => void remove(agent)}
                    >
                      <Button danger>删除</Button>
                    </Popconfirm>
                  </div>
                </Card>
              </List.Item>
            )}
          />
        )}
      </div>
      </section>

      <Modal
        title={`编辑 ${editing?.name ?? "Agent"}`}
        open={Boolean(editing)}
        onCancel={() => setEditing(null)}
        onOk={() => editForm.submit()}
        confirmLoading={saving}
        destroyOnHidden
      >
        <AgentForm
          form={editForm}
          providers={enabledProviders}
          models={editModels}
          onProviderChange={() => editForm.setFieldValue("model_id", undefined)}
          onFinish={saveEdit}
          saving={saving}
          hideSubmit
        />
      </Modal>

      <Modal
        title={`${workspaceAgent?.name ?? "Agent"} · Workspace`}
        open={Boolean(workspaceAgent)}
        onCancel={() => {
          setWorkspaceAgent(null);
          setWorkspaceFile(null);
        }}
        width={900}
        footer={
          <Space>
            <Text type="secondary">
              Agent v{workspaceFile?.agent_version ?? workspaceAgent?.version}
            </Text>
            <Button
              type="primary"
              loading={workspaceSaving}
              disabled={!workspaceFile}
              onClick={() => void saveWorkspace()}
            >
              保存 {activeFilename}
            </Button>
          </Space>
        }
      >
        <Tabs
          activeKey={activeFilename}
          items={WORKSPACE_FILES.map((filename) => ({ key: filename, label: filename }))}
          onChange={(filename) => {
            if (workspaceAgent) {
              void loadWorkspaceFile(workspaceAgent, filename as WorkspaceFilename);
            }
          }}
        />
        <TextArea
          className="workspace-editor"
          value={workspaceFile?.content ?? ""}
          disabled={workspaceLoading}
          onChange={(event) =>
            setWorkspaceFile((current) =>
              current ? { ...current, content: event.target.value } : current,
            )
          }
          autoSize={{ minRows: 18, maxRows: 30 }}
        />
      </Modal>
      <AgentCapabilities
        agent={capabilityAgent}
        onClose={() => setCapabilityAgent(null)}
      />
    </div>
  );
}

function ResourceBadge({ icon, label, value }: { icon: ReactNode; label: string; value: number }) {
  return (
    <div className="resource-badge">
      <span>{icon}</span>
      <div><Text type="secondary">{label}</Text><Text strong>{value}</Text></div>
    </div>
  );
}

function AgentForm({
  form,
  providers,
  models,
  onProviderChange,
  onFinish,
  saving,
  submitText,
  hideSubmit = false,
}: {
  form: ReturnType<typeof Form.useForm<AgentFormValues>>[0];
  providers: Provider[];
  models: Array<{ value: string; label: string }>;
  onProviderChange: () => void;
  onFinish: (values: AgentFormValues) => void;
  saving: boolean;
  submitText?: string;
  hideSubmit?: boolean;
}) {
  return (
    <Form
      form={form}
      layout="vertical"
      onFinish={onFinish}
      initialValues={{ is_coordinator: false }}
    >
      <Form.Item name="name" label="Agent 名称" rules={[{ required: true }]}>
        <Input placeholder="例如：行业研究助手" />
      </Form.Item>
      <Form.Item name="description" label="用途说明" rules={[{ max: 1000 }]}>
        <TextArea autoSize={{ minRows: 2, maxRows: 5 }} />
      </Form.Item>
      <Form.Item name="provider_id" label="Provider" rules={[{ required: true }]}>
        <Select
          options={providers.map((provider) => ({ value: provider.id, label: provider.name }))}
          onChange={onProviderChange}
        />
      </Form.Item>
      <Form.Item name="model_id" label="Model" rules={[{ required: true }]}>
        <Select options={models} disabled={!models.length} />
      </Form.Item>
      <Form.Item name="is_coordinator" valuePropName="checked" className="agent-coordinator-field">
        <Checkbox>作为协调 Agent（可在 Team 中获得受控委派能力）</Checkbox>
      </Form.Item>
      {!hideSubmit && (
        <div className="agent-create-submit">
          <Button type="primary" htmlType="submit" loading={saving} disabled={!providers.length}>
            {submitText}
          </Button>
        </div>
      )}
    </Form>
  );
}

function modelsFor(
  providers: Provider[],
  providerId?: string,
): Array<{ value: string; label: string }> {
  return (
    providers
      .find((provider) => provider.id === providerId)
      ?.models.filter((model) => model.enabled)
      .map((model) => ({ value: model.id, label: model.display_name })) ?? []
  );
}

function errorText(reason: unknown): string {
  return reason instanceof Error ? reason.message : "发生未知错误";
}
