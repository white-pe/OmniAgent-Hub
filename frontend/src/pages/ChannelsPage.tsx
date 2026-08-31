import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Collapse,
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
  Tabs,
  Tag,
  Typography,
  message,
} from "antd";

import { listAgents, type Agent } from "../api/agents";
import {
  createChannel,
  createWeComBot,
  deleteChannel,
  listChannelMessages,
  listChannels,
  pollWeComBotQr,
  retryChannelMessage,
  rotateChannelSecrets,
  rotateWeComBotCredentials,
  sendDebugInbound,
  setChannelStatus,
  startWeComBotQr,
  updateChannel,
  updateWeComBot,
  type Channel,
  type ChannelMessage,
  type DebugInboundInput,
  type WeComBotInput,
  type WeComChannelInput,
  type WeComQrStart,
} from "../api/channels";

const { Paragraph, Text, Title } = Typography;
const { TextArea } = Input;
type AppPublicInput = Pick<
  WeComChannelInput,
  "name" | "agent_id" | "corp_id" | "wecom_agent_id"
>;
type AppSecretInput = Pick<
  WeComChannelInput,
  "token" | "encoding_aes_key" | "corp_secret"
>;
type BotPublicInput = Pick<WeComBotInput, "name" | "agent_id">;
type BotManualInput = Required<Pick<WeComBotInput, "bot_id" | "secret">>;
type QrAction =
  | { mode: "create"; draft: BotPublicInput }
  | { mode: "rotate"; channel: Channel };

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
  const [qr, setQr] = useState<WeComQrStart | null>(null);
  const [qrAction, setQrAction] = useState<QrAction | null>(null);
  const [qrHint, setQrHint] = useState("等待扫码确认…");
  const [botQrForm] = Form.useForm<BotPublicInput>();
  const [botManualForm] = Form.useForm<WeComBotInput>();
  const [appCreateForm] = Form.useForm<WeComChannelInput>();
  const [appEditForm] = Form.useForm<AppPublicInput>();
  const [botEditForm] = Form.useForm<BotPublicInput>();
  const [appSecretForm] = Form.useForm<AppSecretInput>();
  const [botSecretForm] = Form.useForm<BotManualInput>();
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

  useEffect(() => {
    if (!qr || !qrAction) return;
    let active = true;
    let inFlight = false;
    let terminal = false;
    const poll = async () => {
      if (!active || inFlight || terminal) return;
      inFlight = true;
      try {
        const result = await pollWeComBotQr(qr.auth_session_id);
        if (!active) return;
        if (result.status === "waiting") return;
        if (result.status === "ready") {
          terminal = true;
          active = false;
          setQrHint("授权成功，正在创建连接…");
          setSaving(true);
          if (qrAction.mode === "create") {
            await createWeComBot({
              ...qrAction.draft,
              auth_session_id: qr.auth_session_id,
            });
            botQrForm.resetFields();
            void message.success("智能机器人 Channel 已创建");
          } else {
            await rotateWeComBotCredentials(qrAction.channel, {
              auth_session_id: qr.auth_session_id,
            });
            void message.success("机器人凭据已重新授权");
          }
          setQr(null);
          setQrAction(null);
          await refresh();
          return;
        }
        terminal = true;
        setQrHint(result.message ?? "授权未完成，请重新获取二维码");
      } catch (reason) {
        terminal = true;
        setQrHint(errorText(reason));
      } finally {
        inFlight = false;
        setSaving(false);
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 3000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [qr, qrAction, botQrForm]);

  const beginQr = async (action: QrAction) => {
    setSaving(true);
    try {
      const nextQr = await startWeComBotQr();
      setQrAction(action);
      setQrHint("等待扫码确认…");
      setQr(nextQr);
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setSaving(false);
    }
  };

  const createManualBot = async (values: WeComBotInput) => {
    setSaving(true);
    try {
      await createWeComBot(values);
      botManualForm.resetFields();
      void message.success("智能机器人 Channel 已创建");
      await refresh();
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setSaving(false);
    }
  };

  const createAppChannel = async (values: WeComChannelInput) => {
    setSaving(true);
    try {
      await createChannel(values);
      appCreateForm.resetFields();
      void message.success("自建应用 Channel 已创建");
      await refresh();
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setSaving(false);
    }
  };

  const openEdit = (channel: Channel) => {
    setEditing(channel);
    if (channel.kind === "wecom_bot") {
      botEditForm.setFieldsValue({ name: channel.name, agent_id: channel.agent_id });
    } else {
      appEditForm.setFieldsValue({
        name: channel.name,
        agent_id: channel.agent_id,
        corp_id: channel.corp_id ?? "",
        wecom_agent_id: channel.wecom_agent_id ?? undefined,
      });
    }
  };

  const saveBotEdit = async (values: BotPublicInput) => {
    if (!editing) return;
    await save(() => updateWeComBot(editing, values), "Channel 配置已更新", () =>
      setEditing(null),
    );
  };

  const saveAppEdit = async (values: AppPublicInput) => {
    if (!editing) return;
    await save(() => updateChannel(editing, values), "Channel 配置已更新", () =>
      setEditing(null),
    );
  };

  const saveAppSecrets = async (values: AppSecretInput) => {
    if (!rotating) return;
    await save(
      () => rotateChannelSecrets(rotating, values),
      "企业微信应用密钥已轮换",
      () => {
        appSecretForm.resetFields();
        setRotating(null);
      },
    );
  };

  const saveBotSecrets = async (values: BotManualInput) => {
    if (!rotating) return;
    await save(
      () => rotateWeComBotCredentials(rotating, values),
      "机器人凭据已轮换",
      () => {
        botSecretForm.resetFields();
        setRotating(null);
      },
    );
  };

  const save = async (
    operation: () => Promise<unknown>,
    success: string,
    after: () => void,
  ) => {
    setSaving(true);
    try {
      await operation();
      after();
      void message.success(success);
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
    await save(
      async () => {
        const result = await sendDebugInbound(debugging.id, values);
        void message.info(`已创建 Run：${result.run_id ?? "会话正忙"}`);
      },
      "模拟消息已接收",
      () => {
        debugForm.resetFields();
        setDebugging(null);
      },
    );
  };

  return (
    <div className="channel-layout">
      <Alert
        type="info"
        showIcon
        message="推荐：扫码创建企业微信智能机器人"
        description="扫码后由后端取得 Bot ID 与 Secret 并建立 WebSocket 长连接；浏览器不会看到 Secret，也不需要公网 HTTPS 回调地址。"
      />
      <Card title="智能机器人接入流程">
        <Steps
          responsive
          items={[
            { title: "选择 Agent", description: "决定谁来回复消息" },
            { title: "企业微信扫码", description: "管理员确认创建机器人" },
            { title: "后端安全保存", description: "Bot Secret 加密落盘" },
            { title: "长连接收发", description: "无需配置回调 URL" },
          ]}
        />
      </Card>

      <Card title="创建智能机器人 Channel" className="channel-form-card">
        <Tabs
          items={[
            {
              key: "qr",
              label: "扫码授权（推荐）",
              children: (
                <Form
                  form={botQrForm}
                  layout="vertical"
                  onFinish={(values) => void beginQr({ mode: "create", draft: values })}
                >
                  <BotPublicFields agents={agents} />
                  <Alert
                    type="warning"
                    showIcon
                    message="扫码时若企业微信询问是否授权额外能力，先选择“暂不授权”，避免机器人仅创建者可用。"
                  />
                  <Button type="primary" htmlType="submit" loading={saving}>
                    扫码授权并创建
                  </Button>
                </Form>
              ),
            },
            {
              key: "manual",
              label: "手工填写 Bot ID / Secret",
              children: (
                <Form
                  form={botManualForm}
                  layout="vertical"
                  onFinish={createManualBot}
                >
                  <BotPublicFields agents={agents} />
                  <BotSecretFields />
                  <Button type="primary" htmlType="submit" loading={saving}>
                    创建并连接
                  </Button>
                </Form>
              ),
            },
          ]}
        />
      </Card>

      <Collapse
        items={[
          {
            key: "callback",
            label: "高级：使用企业微信自建应用回调模式",
            children: (
              <>
                <Paragraph type="secondary">
                  兼容上一阶段方案，需要 CorpID、AgentId、应用 Secret、回调 Token、
                  EncodingAESKey 与公网 HTTPS 地址。
                </Paragraph>
                <Form
                  form={appCreateForm}
                  layout="vertical"
                  onFinish={createAppChannel}
                >
                  <AppPublicFields agents={agents} />
                  <AppSecretFields />
                  <Button type="primary" htmlType="submit" loading={saving}>
                    创建自建应用 Channel
                  </Button>
                </Form>
              </>
            ),
          },
        ]}
      />

      <Card title={`Channel 列表（${channels.length}）`} loading={loading}>
        {!channels.length && !loading ? (
          <Empty description="还没有企业微信 Channel" />
        ) : (
          <List
            grid={{ gutter: 16, xs: 1, lg: 2 }}
            dataSource={channels}
            renderItem={(channel) => <ChannelCard channel={channel} />}
          />
        )}
      </Card>

      <Modal
        title={`编辑 ${editing?.name ?? "Channel"}`}
        open={Boolean(editing)}
        onCancel={() => setEditing(null)}
        onOk={() =>
          editing?.kind === "wecom_bot" ? botEditForm.submit() : appEditForm.submit()
        }
        confirmLoading={saving}
      >
        {editing?.kind === "wecom_bot" ? (
          <Form form={botEditForm} layout="vertical" onFinish={saveBotEdit}>
            <BotPublicFields agents={agents} />
          </Form>
        ) : (
          <Form form={appEditForm} layout="vertical" onFinish={saveAppEdit}>
            <AppPublicFields agents={agents} />
          </Form>
        )}
      </Modal>

      <Modal
        title={`更新 ${rotating?.name ?? "Channel"} 的凭据`}
        open={Boolean(rotating)}
        onCancel={() => setRotating(null)}
        footer={null}
      >
        {rotating?.kind === "wecom_bot" ? (
          <Tabs
            items={[
              {
                key: "qr",
                label: "重新扫码",
                children: (
                  <Button
                    type="primary"
                    loading={saving}
                    onClick={() => {
                      const channel = rotating;
                      setRotating(null);
                      void beginQr({ mode: "rotate", channel });
                    }}
                  >
                    获取新的授权二维码
                  </Button>
                ),
              },
              {
                key: "manual",
                label: "手工填写",
                children: (
                  <Form
                    form={botSecretForm}
                    layout="vertical"
                    onFinish={saveBotSecrets}
                  >
                    <BotSecretFields />
                    <Button type="primary" htmlType="submit" loading={saving}>
                      保存并重连
                    </Button>
                  </Form>
                ),
              },
            ]}
          />
        ) : (
          <Form
            form={appSecretForm}
            layout="vertical"
            onFinish={saveAppSecrets}
          >
            <AppSecretFields />
            <Button type="primary" htmlType="submit" loading={saving}>
              保存密钥
            </Button>
          </Form>
        )}
      </Modal>

      <Modal
        title={`模拟 ${debugging?.name ?? "Channel"} 入站消息`}
        open={Boolean(debugging)}
        onCancel={() => setDebugging(null)}
        onOk={() => debugForm.submit()}
        confirmLoading={saving}
      >
        <Form form={debugForm} layout="vertical" onFinish={debug}>
          <Form.Item name="external_user_id" label="企业微信 UserID" rules={[{ required: true }]}>
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

      <Modal
        title="扫码授权企业微信机器人"
        open={Boolean(qr)}
        onCancel={() => {
          setQr(null);
          setQrAction(null);
        }}
        footer={null}
      >
        <div style={{ textAlign: "center" }}>
          <Title level={5}>请使用企业微信扫码并确认</Title>
          {qr && <img src={qr.qrcode_image} alt="企业微信机器人授权二维码" width={260} />}
          <Paragraph>{qrHint}</Paragraph>
          <Text type="secondary">二维码约 {qr?.expires_in ?? 0} 秒后过期</Text>
        </div>
      </Modal>
    </div>
  );

  function ChannelCard({ channel }: { channel: Channel }) {
    const isBot = channel.kind === "wecom_bot";
    return (
      <List.Item>
        <Card
          className="channel-card"
          title={
            <Space wrap>
              <Text strong>{channel.name}</Text>
              <Tag color={isBot ? "orange" : "green"}>
                {isBot ? "智能机器人" : "自建应用"}
              </Tag>
              <Tag color={channel.status === "active" ? "success" : "default"}>
                {channel.status === "active" ? "已启用" : "已停用"}
              </Tag>
              {isBot && <ConnectionTag value={channel.connection_status} />}
            </Space>
          }
          extra={
            <Switch
              checked={channel.status === "active"}
              onChange={(checked) =>
                void setChannelStatus(channel, checked ? "active" : "disabled").then(
                  refresh,
                  (reason: unknown) => message.error(errorText(reason)),
                )
              }
            />
          }
        >
          <Descriptions size="small" column={1}>
            <Descriptions.Item label="绑定 Agent">{channel.agent_name}</Descriptions.Item>
            {isBot ? (
              <Descriptions.Item label="Bot ID">
                <Text code>{channel.bot_id_masked}</Text>
              </Descriptions.Item>
            ) : (
              <>
                <Descriptions.Item label="CorpID">
                  <Text code>{channel.corp_id}</Text>
                </Descriptions.Item>
                <Descriptions.Item label="应用 AgentId">
                  {channel.wecom_agent_id}
                </Descriptions.Item>
                <Descriptions.Item label="回调路径">
                  <Text copyable={{ text: channel.callback_path ?? "" }}>
                    {channel.callback_path}
                  </Text>
                </Descriptions.Item>
              </>
            )}
          </Descriptions>
          <div className="agent-actions">
            <Button onClick={() => openEdit(channel)}>编辑配置</Button>
            <Button onClick={() => setRotating(channel)}>
              {isBot ? "重新授权" : "轮换密钥"}
            </Button>
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
  }
}

function BotPublicFields({ agents }: { agents: Agent[] }) {
  return (
    <>
      <Form.Item name="name" label="Channel 名称" rules={[{ required: true }]}>
        <Input placeholder="例如：团队智能助理" />
      </Form.Item>
      <AgentField agents={agents} />
    </>
  );
}

function BotSecretFields() {
  return (
    <>
      <Form.Item name="bot_id" label="Bot ID" rules={[{ required: true }]}>
        <Input />
      </Form.Item>
      <Form.Item name="secret" label="Secret" rules={[{ required: true }]}>
        <Input.Password />
      </Form.Item>
    </>
  );
}

function AppPublicFields({ agents }: { agents: Agent[] }) {
  return (
    <>
      <Form.Item name="name" label="Channel 名称" rules={[{ required: true }]}>
        <Input placeholder="例如：内部工作助理" />
      </Form.Item>
      <AgentField agents={agents} />
      <Form.Item name="corp_id" label="企业 CorpID" rules={[{ required: true }]}>
        <Input />
      </Form.Item>
      <Form.Item name="wecom_agent_id" label="自建应用 AgentId" rules={[{ required: true }]}>
        <InputNumber min={1} className="full-width" />
      </Form.Item>
    </>
  );
}

function AgentField({ agents }: { agents: Agent[] }) {
  return (
    <Form.Item name="agent_id" label="绑定 Agent" rules={[{ required: true }]}>
      <Select options={agents.map((agent) => ({ value: agent.id, label: agent.name }))} />
    </Form.Item>
  );
}

function AppSecretFields() {
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

function ConnectionTag({ value }: { value: Channel["connection_status"] }) {
  const view = {
    connected: ["success", "已连接"],
    connecting: ["processing", "连接中"],
    error: ["error", "连接异常"],
    stopped: ["default", "未连接"],
    not_applicable: ["default", "不适用"],
  }[value];
  return <Tag color={view[0]}>{view[1]}</Tag>;
}

function errorText(reason: unknown): string {
  return reason instanceof Error ? reason.message : "发生未知错误";
}
