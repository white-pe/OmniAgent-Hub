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
  Select,
  Space,
  Switch,
  Tag,
  Typography,
  message,
} from "antd";

import { listAgents, type Agent } from "../api/agents";
import {
  createTeam,
  deleteTeam,
  listTeams,
  toggleTeam,
  updateTeam,
  type Team,
  type TeamInput,
} from "../api/teams";

const { Paragraph, Text } = Typography;
const { TextArea } = Input;

export default function TeamsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState<Team | null>(null);
  const [createForm] = Form.useForm<TeamInput>();
  const [editForm] = Form.useForm<TeamInput>();
  const createCoordinator = Form.useWatch("coordinator_agent_id", createForm);
  const editCoordinator = Form.useWatch("coordinator_agent_id", editForm);

  const refresh = async () => {
    setLoading(true);
    try {
      const [nextAgents, nextTeams] = await Promise.all([listAgents(), listTeams()]);
      setAgents(nextAgents);
      setTeams(nextTeams);
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const create = async (values: TeamInput) => {
    setSaving(true);
    try {
      await createTeam(values);
      createForm.resetFields();
      void message.success("Team 已创建，协调 Agent 获得受控委派能力");
      await refresh();
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setSaving(false);
    }
  };

  const openEdit = (team: Team) => {
    setEditing(team);
    editForm.setFieldsValue({
      name: team.name,
      description: team.description,
      coordinator_agent_id: team.coordinator_agent_id,
      member_agent_ids: team.members
        .filter((member) => member.role === "member")
        .map((member) => member.agent_id),
    });
  };

  const saveEdit = async (values: TeamInput) => {
    if (!editing) return;
    setSaving(true);
    try {
      await updateTeam(editing, values);
      setEditing(null);
      void message.success("Team 配置已更新");
      await refresh();
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setSaving(false);
    }
  };

  const changeStatus = async (team: Team) => {
    try {
      await toggleTeam(team.id);
      await refresh();
    } catch (reason) {
      void message.error(errorText(reason));
    }
  };

  const remove = async (team: Team) => {
    try {
      await deleteTeam(team.id);
      void message.success("未使用的 Team 已删除");
      await refresh();
    } catch (reason) {
      void message.error(errorText(reason));
    }
  };

  const activeAgents = agents.filter((agent) => agent.status === "active");
  const coordinators = activeAgents.filter((agent) => agent.is_coordinator);

  return (
    <div className="team-layout">
      <Alert
        type="info"
        showIcon
        title="Team 是委派白名单，不是共享权限容器。"
        description="成员子 Run 使用自己的模型、Workspace、Skills 和 Tools；协调 Agent 只能收到成员最终结果。"
      />
      {!coordinators.length && (
        <Alert
          type="warning"
          showIcon
          title="请先把至少一个 Agent 标记为协调 Agent。"
        />
      )}

      <Card title="创建 Team" className="team-form-card">
        <TeamForm
          form={createForm}
          coordinators={coordinators}
          members={activeAgents.filter((agent) => agent.id !== createCoordinator)}
          onFinish={create}
          saving={saving}
        />
      </Card>

      <Card title={`Team 列表（${teams.length}）`} loading={loading}>
        {!teams.length && !loading ? (
          <Empty description="还没有 Team" />
        ) : (
          <List
            grid={{ gutter: 16, xs: 1, md: 2 }}
            dataSource={teams}
            renderItem={(team) => (
              <List.Item>
                <Card
                  className="team-card"
                  title={
                    <Space wrap>
                      <Text strong>{team.name}</Text>
                      <Tag color={team.status === "active" ? "success" : "default"}>
                        {team.status === "active" ? "可委派" : "已停用"}
                      </Tag>
                    </Space>
                  }
                  extra={
                    <Switch
                      checked={team.status === "active"}
                      onChange={() => void changeStatus(team)}
                    />
                  }
                >
                  <Paragraph>{team.description || "暂无 Team 说明"}</Paragraph>
                  <Text type="secondary">协调 Agent</Text>
                  <Paragraph><Tag color="purple">{team.coordinator_agent_name}</Tag></Paragraph>
                  <Text type="secondary">可委派成员</Text>
                  <div className="team-members">
                    {team.members
                      .filter((member) => member.role === "member")
                      .map((member) => <Tag key={member.agent_id}>{member.agent_name}</Tag>)}
                  </div>
                  <div className="agent-actions">
                    <Button onClick={() => openEdit(team)}>编辑 Team</Button>
                    <Popconfirm
                      title="仅没有委派历史的 Team 可以删除，确定继续？"
                      onConfirm={() => void remove(team)}
                    >
                      <Button danger>删除</Button>
                    </Popconfirm>
                  </div>
                </Card>
              </List.Item>
            )}
          />
        )}
      </Card>

      <Modal
        title={`编辑 ${editing?.name ?? "Team"}`}
        open={Boolean(editing)}
        onCancel={() => setEditing(null)}
        onOk={() => editForm.submit()}
        confirmLoading={saving}
        destroyOnHidden
      >
        <TeamForm
          form={editForm}
          coordinators={coordinators}
          members={activeAgents.filter((agent) => agent.id !== editCoordinator)}
          onFinish={saveEdit}
          saving={saving}
          hideSubmit
        />
      </Modal>
    </div>
  );
}

function TeamForm({
  form,
  coordinators,
  members,
  onFinish,
  saving,
  hideSubmit = false,
}: {
  form: ReturnType<typeof Form.useForm<TeamInput>>[0];
  coordinators: Agent[];
  members: Agent[];
  onFinish: (values: TeamInput) => void;
  saving: boolean;
  hideSubmit?: boolean;
}) {
  return (
    <Form form={form} layout="vertical" onFinish={onFinish}>
      <Form.Item name="name" label="Team 名称" rules={[{ required: true }]}>
        <Input placeholder="例如：内容生产团队" />
      </Form.Item>
      <Form.Item name="description" label="协作目标">
        <TextArea autoSize={{ minRows: 2, maxRows: 5 }} />
      </Form.Item>
      <Form.Item
        name="coordinator_agent_id"
        label="协调 Agent"
        rules={[{ required: true }]}
      >
        <Select
          options={coordinators.map((agent) => ({ value: agent.id, label: agent.name }))}
          onChange={() => form.setFieldValue("member_agent_ids", [])}
        />
      </Form.Item>
      <Form.Item
        name="member_agent_ids"
        label="可委派成员"
        rules={[{ required: true, type: "array", min: 1 }]}
      >
        <Select
          mode="multiple"
          options={members.map((agent) => ({
            value: agent.id,
            label: `${agent.name} · ${agent.description || "未填写职责"}`,
          }))}
        />
      </Form.Item>
      {!hideSubmit && (
        <Button
          type="primary"
          htmlType="submit"
          loading={saving}
          disabled={!coordinators.length}
        >
          创建 Team
        </Button>
      )}
    </Form>
  );
}

function errorText(reason: unknown): string {
  return reason instanceof Error ? reason.message : "发生未知错误";
}
