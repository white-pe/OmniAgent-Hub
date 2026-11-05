import { useEffect, useState, type ReactNode } from "react";
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
import {
  ArrowRight,
  Bot,
  Check,
  Crown,
  Network,
  Plus,
  ShieldCheck,
  Users,
} from "lucide-react";

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
  const activeTeams = teams.filter((team) => team.status === "active").length;
  const totalMembers = teams.reduce(
    (count, team) => count + team.members.filter((member) => member.role === "member").length,
    0,
  );

  return (
    <div className="team-layout">
      <section className="team-page-heading">
        <div>
          <Text className="eyebrow">TEAM ORCHESTRATION / DELEGATION</Text>
          <Typography.Title level={3}>Team 编排</Typography.Title>
          <Text type="secondary">定义协调 Agent 与成员白名单，构建权限边界清晰的协作单元。</Text>
        </div>
        <div className="team-overview-counts">
          <TeamSummary icon={<Network />} label="Team" value={teams.length} />
          <TeamSummary icon={<Check />} label="已启用" value={activeTeams} />
          <TeamSummary icon={<Users />} label="成员关系" value={totalMembers} />
        </div>
      </section>

      <Alert
        type="info"
        showIcon
        className="team-boundary-alert"
        title="委派遵循成员自身权限"
        description="Team 只定义可调用成员白名单，不共享 Workspace、Skills 或 Tools。协调 Agent 接收成员任务结果，子 Run 使用成员自己的模型与能力配置。"
      />
      {!coordinators.length && (
        <Alert
          type="warning"
          showIcon
          title="请先把至少一个 Agent 标记为协调 Agent。"
        />
      )}

      <section className="team-builder">
        <div className="team-builder-heading">
          <span className="team-builder-icon"><Plus size={19} /></span>
          <div>
            <Typography.Title level={4}>创建协作 Team</Typography.Title>
            <Text type="secondary">先选择协调 Agent，再添加允许委派的成员。</Text>
          </div>
        </div>
        <TeamForm
          form={createForm}
          coordinators={coordinators}
          members={activeAgents.filter((agent) => agent.id !== createCoordinator)}
          onFinish={create}
          saving={saving}
        />
      </section>

      <section className="team-list-section">
        <div className="section-title-row">
          <div>
            <Typography.Title level={4}>已配置的 Team</Typography.Title>
            <Text type="secondary">查看编排关系与委派状态</Text>
          </div>
          <Tag>{teams.length} 个</Tag>
        </div>
        <div className="team-list-shell">
        {loading ? <Card loading /> : null}
        {!teams.length && !loading ? (
          <Empty description="还没有 Team" />
        ) : !loading ? (
          <List
            grid={{ gutter: 16, xs: 1, md: 2 }}
            dataSource={teams}
            renderItem={(team) => (
              <List.Item>
                <Card
                  className="team-card"
                  title={
                    <div className="team-card-title">
                      <span className="team-card-mark"><Network size={18} /></span>
                      <div>
                        <Text strong>{team.name}</Text>
                        <Tag color={team.status === "active" ? "success" : "default"}>
                          {team.status === "active" ? "可委派" : "已停用"}
                        </Tag>
                      </div>
                    </div>
                  }
                  extra={
                    <Switch
                      checked={team.status === "active"}
                      onChange={() => void changeStatus(team)}
                    />
                  }
                >
                  <Paragraph className="team-card-description">{team.description || "暂无 Team 说明"}</Paragraph>
                  <div className="team-coordinator-row">
                    <span className="team-role-icon"><Crown size={15} /></span>
                    <div><Text type="secondary">协调 Agent</Text><Text strong>{team.coordinator_agent_name}</Text></div>
                    <ArrowRight size={16} />
                  </div>
                  <div className="team-member-heading">
                    <Text type="secondary">可委派成员</Text>
                    <Tag icon={<Users size={12} />}>{team.members.filter((member) => member.role === "member").length}</Tag>
                  </div>
                  <div className="team-members">
                    {team.members
                      .filter((member) => member.role === "member")
                      .map((member) => (
                        <span className="team-member-chip" key={member.agent_id}>
                          <Bot size={14} /> {member.agent_name}
                        </span>
                      ))}
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
        ) : null}
        </div>
      </section>

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
  const selectedCoordinatorId = Form.useWatch("coordinator_agent_id", form);
  const selectedMemberIds = Form.useWatch("member_agent_ids", form) ?? [];
  const selectedCoordinator = coordinators.find((agent) => agent.id === selectedCoordinatorId);
  const selectedMembers = members.filter((agent) => selectedMemberIds.includes(agent.id));

  return (
    <div className="team-form-layout">
      <Form form={form} layout="vertical" onFinish={onFinish} className="team-form-card">
        <div className="team-form-fields">
          <Form.Item name="name" label="Team 名称" rules={[{ required: true }]}>
            <Input placeholder="例如：产品研究小组" maxLength={100} />
          </Form.Item>
          <Form.Item name="description" label="协作目标">
            <TextArea autoSize={{ minRows: 2, maxRows: 4 }} maxLength={1000} placeholder="描述团队要共同完成的任务" />
          </Form.Item>
          <Form.Item
            name="coordinator_agent_id"
            label="协调 Agent"
            rules={[{ required: true, message: "请选择协调 Agent" }]}
          >
            <Select
              placeholder="选择负责拆解与委派任务的 Agent"
              options={coordinators.map((agent) => ({ value: agent.id, label: agent.name }))}
              onChange={() => form.setFieldValue("member_agent_ids", [])}
            />
          </Form.Item>
          <Form.Item
            name="member_agent_ids"
            label="可委派成员"
            rules={[{ required: true, type: "array", min: 1, message: "至少选择一个成员 Agent" }]}
          >
            <Select
              mode="multiple"
              placeholder="选择可接受子任务的 Agent"
              options={members.map((agent) => ({
                value: agent.id,
                label: `${agent.name} · ${agent.description || "未填写职责"}`,
              }))}
            />
          </Form.Item>
        </div>
        {!hideSubmit && (
          <div className="team-form-footer">
            <Text type="secondary">创建后协调 Agent 才能通过该 Team 调用成员。</Text>
            <Button type="primary" htmlType="submit" loading={saving} disabled={!coordinators.length}>
              创建 Team
            </Button>
          </div>
        )}
      </Form>
      <aside className="team-preview" aria-live="polite">
        <div className="team-preview-heading">
          <ShieldCheck size={17} />
          <Text strong>委派关系预览</Text>
        </div>
        {selectedCoordinator ? (
          <div className="team-preview-flow">
            <div className="team-preview-agent coordinator">
              <Crown size={16} />
              <div><Text strong>{selectedCoordinator.name}</Text><Text type="secondary">协调 Agent</Text></div>
            </div>
            <div className="team-preview-connector"><span />允许委派<span /></div>
            {selectedMembers.length ? selectedMembers.map((agent) => (
              <div className="team-preview-agent" key={agent.id}>
                <Bot size={16} />
                <div><Text strong>{agent.name}</Text><Text type="secondary">{agent.description || "成员 Agent"}</Text></div>
              </div>
            )) : <Text className="team-preview-empty" type="secondary">选择成员后将在此显示委派范围</Text>}
          </div>
        ) : (
          <div className="team-preview-placeholder">
            <Network size={24} />
            <Text type="secondary">选择协调 Agent 与成员，预览协作关系</Text>
          </div>
        )}
        <div className="team-preview-note">
          <ShieldCheck size={14} />
          <Text type="secondary">成员运行时使用自己的模型与能力权限</Text>
        </div>
      </aside>
    </div>
  );
}

function TeamSummary({ icon, label, value }: { icon: ReactNode; label: string; value: number }) {
  return <div className="team-summary-item"><span>{icon}</span><div><Text type="secondary">{label}</Text><Text strong>{value}</Text></div></div>;
}

function errorText(reason: unknown): string {
  return reason instanceof Error ? reason.message : "发生未知错误";
}
