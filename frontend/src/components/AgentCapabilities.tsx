import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Space,
  Spin,
  Switch,
  Tabs,
  Tag,
  Typography,
  message,
} from "antd";

import type { Agent } from "../api/agents";
import {
  createSkill,
  deleteSkill,
  listSkills,
  toggleSkill,
  updateSkill,
  type Skill,
  type SkillInput,
} from "../api/skills";
import { listTools, toggleTool, type ToolAssignment } from "../api/tools";

const { Paragraph, Text } = Typography;
const { TextArea } = Input;

type SkillFormValues = Pick<SkillInput, "name" | "description" | "content">;

export default function AgentCapabilities({
  agent,
  onClose,
}: {
  agent: Agent | null;
  onClose: () => void;
}) {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [tools, setTools] = useState<ToolAssignment[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [skillEditorOpen, setSkillEditorOpen] = useState(false);
  const [editingSkill, setEditingSkill] = useState<Skill | null>(null);
  const [form] = Form.useForm<SkillFormValues>();

  const refresh = async (currentAgent: Agent) => {
    setLoading(true);
    try {
      const [nextSkills, nextTools] = await Promise.all([
        listSkills(currentAgent.id),
        listTools(currentAgent.id),
      ]);
      setSkills(nextSkills);
      setTools(nextTools);
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (agent) void refresh(agent);
    else {
      setSkills([]);
      setTools([]);
    }
  }, [agent]);

  const openNewSkill = () => {
    setEditingSkill(null);
    form.resetFields();
    setSkillEditorOpen(true);
  };

  const openEditSkill = (skill: Skill) => {
    setEditingSkill(skill);
    form.setFieldsValue({
      name: skill.name,
      description: skill.description,
      content: skill.content,
    });
    setSkillEditorOpen(true);
  };

  const saveSkill = async (values: SkillFormValues) => {
    if (!agent) return;
    setSaving(true);
    try {
      if (editingSkill) {
        await updateSkill(agent.id, editingSkill, {
          description: values.description,
          content: values.content,
        });
      } else {
        await createSkill(agent.id, {
          ...values,
          enabled: true,
          channel_scope: ["console"],
        });
      }
      setSkillEditorOpen(false);
      void message.success(editingSkill ? "Skill 已更新" : "Skill 已创建并启用");
      await refresh(agent);
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setSaving(false);
    }
  };

  const changeSkill = async (skill: Skill) => {
    if (!agent) return;
    try {
      await toggleSkill(agent.id, skill.name);
      await refresh(agent);
    } catch (reason) {
      void message.error(errorText(reason));
    }
  };

  const removeSkill = async (skill: Skill) => {
    if (!agent) return;
    try {
      await deleteSkill(agent.id, skill.name);
      void message.success("Skill 元数据和目录已删除");
      await refresh(agent);
    } catch (reason) {
      void message.error(errorText(reason));
    }
  };

  const changeTool = async (tool: ToolAssignment) => {
    if (!agent) return;
    try {
      await toggleTool(agent.id, tool.name);
      await refresh(agent);
    } catch (reason) {
      void message.error(errorText(reason));
    }
  };

  return (
    <>
      <Modal
        title={`${agent?.name ?? "Agent"} · Skills 与 Tools`}
        open={Boolean(agent)}
        onCancel={onClose}
        footer={null}
        width={940}
        destroyOnHidden
      >
        <Alert
          type="info"
          showIcon
          message="Skill 决定怎么做；Tool 决定能做什么。"
          description="两者都按 Agent 隔离。新 Tool 默认关闭，运行时还会再次校验权限、参数、路径、超时和结果大小。"
        />
        {loading ? (
          <div className="capability-loading"><Spin /></div>
        ) : (
          <Tabs
            className="capability-tabs"
            items={[
              {
                key: "skills",
                label: `Skills（${skills.length}）`,
                children: (
                  <>
                    <Button type="primary" onClick={openNewSkill}>
                      新建 Skill
                    </Button>
                    {!skills.length ? (
                      <Empty description="还没有 Skill" />
                    ) : (
                      <List
                        className="capability-list"
                        dataSource={skills}
                        renderItem={(skill) => (
                          <List.Item>
                            <Card className="capability-card">
                              <div className="capability-title">
                                <Space wrap>
                                  <Text strong>{skill.name}</Text>
                                  <Tag color={skill.enabled ? "success" : "default"}>
                                    {skill.enabled ? "已注入 Prompt" : "已停用"}
                                  </Tag>
                                  <Tag>v{skill.version}</Tag>
                                </Space>
                                <Switch
                                  checked={skill.enabled}
                                  onChange={() => void changeSkill(skill)}
                                />
                              </div>
                              <Paragraph>{skill.description}</Paragraph>
                              <Text type="secondary" code>{skill.path}/SKILL.md</Text>
                              <div className="capability-actions">
                                <Button onClick={() => openEditSkill(skill)}>编辑</Button>
                                <Popconfirm
                                  title="删除这个 Skill 及其目录？"
                                  onConfirm={() => void removeSkill(skill)}
                                >
                                  <Button danger>删除</Button>
                                </Popconfirm>
                              </div>
                            </Card>
                          </List.Item>
                        )}
                      />
                    )}
                  </>
                ),
              },
              {
                key: "tools",
                label: `Tools（${tools.filter((tool) => tool.enabled).length}/${tools.length}）`,
                children: (
                  <List
                    className="capability-list"
                    dataSource={tools}
                    locale={{ emptyText: "服务端尚未注册 Tool" }}
                    renderItem={(tool) => (
                      <List.Item>
                        <Card className="capability-card">
                          <div className="capability-title">
                            <Space wrap>
                              <Text strong code>{tool.name}</Text>
                              <Tag color={tool.enabled ? "processing" : "default"}>
                                {tool.enabled ? "已授权" : "默认关闭"}
                              </Tag>
                            </Space>
                            <Switch
                              checked={tool.enabled}
                              onChange={() => void changeTool(tool)}
                            />
                          </div>
                          <Paragraph>{tool.description}</Paragraph>
                          <Text type="secondary">
                            参数由 Pydantic 根据 JSON Schema 二次校验
                          </Text>
                        </Card>
                      </List.Item>
                    )}
                  />
                ),
              },
            ]}
          />
        )}
      </Modal>

      <Modal
        title={editingSkill ? `编辑 ${editingSkill.name}` : "新建 Skill"}
        open={skillEditorOpen}
        onCancel={() => setSkillEditorOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={saving}
        width={760}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={saveSkill}>
          <Form.Item
            name="name"
            label="Skill 标识"
            extra="小写字母、数字、- 或 _；创建后不可修改，也是目录名。"
            rules={[{ required: true, pattern: /^[a-z0-9][a-z0-9_-]*$/ }]}
          >
            <Input disabled={Boolean(editingSkill)} placeholder="research-checklist" />
          </Form.Item>
          <Form.Item
            name="description"
            label="用途说明"
            rules={[{ required: true, max: 500 }]}
          >
            <Input placeholder="何时使用、解决什么问题" />
          </Form.Item>
          <Form.Item name="content" label="SKILL.md" rules={[{ required: true }]}>
            <TextArea
              className="workspace-editor"
              autoSize={{ minRows: 14, maxRows: 24 }}
              placeholder="# 工作流程\n\n1. ...\n2. ..."
            />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

function errorText(reason: unknown): string {
  return reason instanceof Error ? reason.message : "发生未知错误";
}
