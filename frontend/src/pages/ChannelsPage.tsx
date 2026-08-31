import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Popconfirm,
  Select,
  Space,
  Steps,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from "antd";

import { listAgents, type Agent } from "../api/agents";
import {
  createChannel,
  deleteChannel,
  listChannelMessages,
  listChannels,
  retryChannelMessage,
  rotateChannelSecrets,
  sendDebugInbound,
  setChannelStatus,
  updateChannel,
  type Channel,
  type ChannelMessage,
  type DebugInboundInput,
  type WeComChannelInput,
} from "../api/channels";

const { Paragraph, Text } = Typography;
const { TextArea } = Input;
type PublicInput = Pick<
  WeComChannelInput,
  "name" | "agent_id" | "corp_id" | "wecom_agent_id"
>;
type SecretInput = Pick<
  WeComChannelInput,
  "token" | "encoding_aes_key" | "corp_secret"
>;

export default function ChannelsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState<Channel | null>(null);
  const [rotating, setRotating] = useState<Channel | null>(null);
  const [debugging, setDebugging] = useState<Channel | null>(null);
  const [inspecting, setInspecting] = useState<Channel | null>(null);
  const [channelMessages, setChannelMessages] = useState<ChannelMessage[]>([]);
  const [createForm] = Form.useForm<WeComChannelInput>();
  const [editForm] = Form.useForm<PublicInput>();
  const [secretForm] = Form.useForm<SecretInput>();
  const [debugForm] = Form.useForm<DebugInboundInput>();

  const refresh = async () => {
    setLoading(true);
    try {
      const [nextAgents, nextChannels] = await Promise.all([
        listAgents(),
        listChannels(),
      ]);
      setAgents(nextAgents.filter((agent) => agent.status === "active"));
      setChannels(nextChannels);
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const create = async (values: WeComChannelInput) => {
    setSaving(true);
    try {
      await createChannel(values);
      createForm.resetFields();
      void message.success("企业微信 Channel 已创建");
      await refresh();
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setSaving(false);
    }
  };

  const openEdit = (channel: Channel) => {
    setEditing(channel);
    editForm.setFieldsValue({
      name: channel.name,
      agent_id: channel.agent_id,
      corp_id: channel.corp_id,
      wecom_agent_id: channel.wecom_agent_id,
    });
  };

  const saveEdit = async (values: PublicInput) => {
    if (!editing) return;
    setSaving(true);
    try {
      await updateChannel(editing, values);
      setEditing(null);
      void message.success("Channel 配置已更新");
      await refresh();
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setSaving(false);
    }
  };

  const saveSecrets = async (values: SecretInput) => {
    if (!rotating) return;
    setSaving(true);
    try {
      await rotateChannelSecrets(rotating, values);
      secretForm.resetFields();
      setRotating(null);
      void message.success("企业微信密钥已轮换");
      await refresh();
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setSaving(false);
    }
  };

  const inspect = async (channel: Channel) => {
    setInspecting(channel);
    try {
      setChannelMessages(await listChannelMessages(channel.id));
    } catch (reason) {
      void message.error(errorText(reason));
    }
  };

  const debug = async (values: DebugInboundInput) => {
    if (!debugging) return;
    setSaving(true);
    try {
      const result = await sendDebugInbound(debugging.id, values);
      debugForm.resetFields();
      setDebugging(null);
      void message.success(`已创建 Run：${result.run_id ?? "会话正忙"}`);
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="channel-layout">
      <Alert
        type="info"
        showIcon
        message="本阶段接入企业微信自建应用。"
        description="企业微信回调只负责验签、解密、落库并快速返回 success；模型在后台运行，完成后再通过应用消息 API 主动回复。"
      />
      <Card title="企业微信后台配置顺序">
        <Steps
          responsive
          items={[
            { title: "创建自建应用", description: "取得 CorpID、AgentId、Secret" },
            { title: "创建 Channel", description: "填写回调 Token 与 EncodingAESKey" },
            { title: "暴露 HTTPS", description: "让公网地址转发到本项目 /api" },
            { title: "保存回调 URL", description: "企业微信发起 GET 验证" },
          ]}
        />
      </Card>

      <Card title="创建企业微信 Channel" className="channel-form-card">
        <WeComForm
          form={createForm}
          agents={agents}
          onFinish={create}
          saving={saving}
          includeSecrets
        />
      </Card>

      <Card title={`Channel 列表（${channels.length}）`} loading={loading}>
        {!channels.length && !loading ? (
          <Empty description="还没有企业微信 Channel" />
        ) : (
          <List
            grid={{ gutter: 16, xs: 1, lg: 2 }}
            dataSource={channels}
            renderItem={(channel) => {
              return (
                <List.Item>
                  <Card
                    className="channel-card"
                    title={
                      <Space wrap>
                        <Text strong>{channel.name}</Text>
                        <Tag color="green">企业微信</Tag>
                        <Tag color={channel.status === "active" ? "success" : "default"}>
                          {channel.status === "active" ? "接收中" : "已停用"}
                        </Tag>
                      </Space>
                    }
                    extra={
                      <Switch
                        checked={channel.status === "active"}
                        onChange={(checked) =>
                          void setChannelStatus(
                            channel,
                            checked ? "active" : "disabled",
                          ).then(refresh, (reason: unknown) =>
                            message.error(errorText(reason)),
                          )
                        }
                      />
                    }
                  >
                    <Descriptions size="small" column={1}>
                      <Descriptions.Item label="绑定 Agent">
                        {channel.agent_name}
                      </Descriptions.Item>
                      <Descriptions.Item label="CorpID">
                        <Text code>{channel.corp_id}</Text>
                      </Descriptions.Item>
                      <Descriptions.Item label="应用 AgentId">
                        {channel.wecom_agent_id}
                      </Descriptions.Item>
                      <Descriptions.Item label="回调路径">
                        <Text
                          copyable={{ text: channel.callback_path }}
                          className="callback-url"
                        >
                          {channel.callback_path}
                        </Text>
                      </Descriptions.Item>
                    </Descriptions>
                    <div className="agent-actions">
                      <Button onClick={() => openEdit(channel)}>编辑配置</Button>
                      <Button onClick={() => setRotating(channel)}>轮换密钥</Button>
                      <Button onClick={() => setDebugging(channel)}>模拟入站</Button>
                      <Button onClick={() => void inspect(channel)}>消息日志</Button>
                      <Popconfirm
                        title="只有没有消息历史的 Channel 才能删除，确定继续？"
                        onConfirm={() =>
                          void deleteChannel(channel.id).then(refresh, (reason: unknown) =>
                            message.error(errorText(reason)),
                          )
                        }
                      >
                        <Button danger>删除</Button>
                      </Popconfirm>
                    </div>
                  </Card>
                </List.Item>
              );
            }}
          />
        )}
      </Card>

      <Modal
        title={`编辑 ${editing?.name ?? "Channel"}`}
        open={Boolean(editing)}
        onCancel={() => setEditing(null)}
        onOk={() => editForm.submit()}
        confirmLoading={saving}
      >
        <WeComForm
          form={editForm}
          agents={agents}
          onFinish={saveEdit}
          saving={saving}
          hideSubmit
        />
      </Modal>
      <Modal
        title={`轮换 ${rotating?.name ?? "Channel"} 的三项密钥`}
        open={Boolean(rotating)}
        onCancel={() => setRotating(null)}
        onOk={() => secretForm.submit()}
        confirmLoading={saving}
      >
        <Form form={secretForm} layout="vertical" onFinish={saveSecrets}>
          <SecretFields />
        </Form>
      </Modal>
      <Modal
        title={`模拟 ${debugging?.name ?? "Channel"} 入站消息`}
        open={Boolean(debugging)}
        onCancel={() => setDebugging(null)}
        onOk={() => debugForm.submit()}
        confirmLoading={saving}
      >
        <Form form={debugForm} layout="vertical" onFinish={debug}>
          <Form.Item
            name="external_user_id"
            label="企业微信 UserID"
            rules={[{ required: true }]}
          >
            <Input placeholder="例如：zhangsan" />
          </Form.Item>
          <Form.Item name="content" label="消息正文" rules={[{ required: true }]}>
            <TextArea autoSize={{ minRows: 3, maxRows: 8 }} />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title={`${inspecting?.name ?? "Channel"} · 消息日志`}
        open={Boolean(inspecting)}
        onCancel={() => setInspecting(null)}
        footer={<Button onClick={() => inspecting && void inspect(inspecting)}>刷新</Button>}
        width={1000}
      >
        <Table
          rowKey="id"
          size="small"
          pagination={{ pageSize: 8 }}
          dataSource={channelMessages}
          columns={[
            {
              title: "方向",
              dataIndex: "direction",
              render: (value: ChannelMessage["direction"]) => (
                <Tag color={value === "inbound" ? "blue" : "orange"}>{value}</Tag>
              ),
            },
            { title: "用户", dataIndex: "external_user_id", width: 130 },
            { title: "正文", dataIndex: "content", ellipsis: true },
            { title: "状态", dataIndex: "status", width: 110 },
            { title: "尝试", dataIndex: "attempts", width: 70 },
            {
              title: "操作",
              width: 90,
              render: (_: unknown, item: ChannelMessage) =>
                item.direction === "outbound" && item.status === "failed" ? (
                  <Button
                    size="small"
                    onClick={() =>
                      void retryChannelMessage(item.id).then(
                        () => inspecting && inspect(inspecting),
                      )
                    }
                  >
                    重试
                  </Button>
                ) : null,
            },
          ]}
        />
      </Modal>
    </div>
  );
}

function WeComForm<T extends PublicInput>({
  form,
  agents,
  onFinish,
  saving,
  includeSecrets = false,
  hideSubmit = false,
}: {
  form: ReturnType<typeof Form.useForm<T>>[0];
  agents: Agent[];
  onFinish: (values: T) => void;
  saving: boolean;
  includeSecrets?: boolean;
  hideSubmit?: boolean;
}) {
  return (
    <Form form={form} layout="vertical" onFinish={onFinish}>
      <Form.Item name="name" label="Channel 名称" rules={[{ required: true }]}>
        <Input placeholder="例如：内部工作助理" />
      </Form.Item>
      <Form.Item name="agent_id" label="绑定 Agent" rules={[{ required: true }]}>
        <Select
          options={agents.map((agent) => ({ value: agent.id, label: agent.name }))}
        />
      </Form.Item>
      <Form.Item name="corp_id" label="企业 CorpID" rules={[{ required: true }]}>
        <Input />
      </Form.Item>
      <Form.Item
        name="wecom_agent_id"
        label="自建应用 AgentId"
        rules={[{ required: true }]}
      >
        <InputNumber min={1} className="full-width" />
      </Form.Item>
      {includeSecrets && <SecretFields />}
      {!hideSubmit && (
        <Button type="primary" htmlType="submit" loading={saving}>
          创建 Channel
        </Button>
      )}
    </Form>
  );
}

function SecretFields() {
  return (
    <>
      <Form.Item name="token" label="回调 Token" rules={[{ required: true }]}>
        <Input.Password maxLength={32} />
      </Form.Item>
      <Form.Item
        name="encoding_aes_key"
        label="EncodingAESKey（43 位）"
        rules={[{ required: true, len: 43 }]}
      >
        <Input.Password maxLength={43} />
      </Form.Item>
      <Form.Item name="corp_secret" label="应用 Secret" rules={[{ required: true }]}>
        <Input.Password />
      </Form.Item>
    </>
  );
}

function errorText(reason: unknown): string {
  return reason instanceof Error ? reason.message : "发生未知错误";
}
