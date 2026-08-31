import { useEffect, useMemo, useState } from "react";
import {
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
  createProvider,
  deleteProvider,
  listProviders,
  streamProviderChat,
  testProvider,
  updateProvider,
  type Provider,
  type ProviderInput,
} from "../api/providers";

const { Paragraph, Text } = Typography;
const { TextArea } = Input;

interface ProviderFormValues {
  name: string;
  base_url: string;
  api_key?: string;
  models_text: string;
}

export default function ProvidersPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Provider | null>(null);
  const [selectedProviderId, setSelectedProviderId] = useState<string>();
  const [selectedModelId, setSelectedModelId] = useState<string>();
  const [prompt, setPrompt] = useState("请用一句话介绍你自己。");
  const [streaming, setStreaming] = useState(false);
  const [output, setOutput] = useState("");
  const [createForm] = Form.useForm<ProviderFormValues>();
  const [editForm] = Form.useForm<ProviderFormValues>();

  const selectedProvider = useMemo(
    () => providers.find((provider) => provider.id === selectedProviderId),
    [providers, selectedProviderId],
  );

  const refresh = async () => {
    setLoading(true);
    try {
      const nextProviders = await listProviders();
      setProviders(nextProviders);
      if (!selectedProviderId && nextProviders[0]) {
        setSelectedProviderId(nextProviders[0].id);
        setSelectedModelId(
          nextProviders[0].models.find((model) => model.enabled)?.id,
        );
      }
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const create = async (values: ProviderFormValues) => {
    setSaving(true);
    try {
      await createProvider(toProviderInput(values, true));
      createForm.resetFields();
      void message.success("Provider 已保存，API Key 不会通过查询接口回传");
      await refresh();
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setSaving(false);
    }
  };

  const saveEdit = async (values: ProviderFormValues) => {
    if (!editing) return;
    setSaving(true);
    try {
      await updateProvider(editing.id, toProviderInput(values, false));
      setEditing(null);
      void message.success("Provider 配置已更新");
      await refresh();
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setSaving(false);
    }
  };

  const openEditor = (provider: Provider) => {
    setEditing(provider);
    editForm.setFieldsValue({
      name: provider.name,
      base_url: provider.base_url,
      api_key: "",
      models_text: provider.models.map((model) => model.model_name).join("\n"),
    });
  };

  const runConnectionTest = async (provider: Provider) => {
    const model = provider.models.find((item) => item.enabled);
    if (!model) {
      void message.error("没有可用模型");
      return;
    }
    setTestingId(provider.id);
    try {
      const result = await testProvider(provider.id, model.id);
      void message.success(
        `${result.model} 连接成功，耗时 ${result.latency_ms} ms，回复：${result.reply_preview}`,
      );
    } catch (reason) {
      void message.error(errorText(reason), 6);
    } finally {
      setTestingId(null);
    }
  };

  const remove = async (providerId: string) => {
    try {
      await deleteProvider(providerId);
      if (selectedProviderId === providerId) {
        setSelectedProviderId(undefined);
        setSelectedModelId(undefined);
      }
      void message.success("Provider 和对应加密密钥已删除");
      await refresh();
    } catch (reason) {
      void message.error(errorText(reason));
    }
  };

  const toggle = async (provider: Provider, enabled: boolean) => {
    try {
      await updateProvider(provider.id, { enabled });
      await refresh();
    } catch (reason) {
      void message.error(errorText(reason));
    }
  };

  const runStream = async () => {
    if (!selectedProviderId || !selectedModelId || !prompt.trim()) return;
    setOutput("");
    setStreaming(true);
    try {
      await streamProviderChat(
        selectedProviderId,
        { model_id: selectedModelId, prompt },
        (event) => {
          if (event.event === "delta") {
            setOutput((current) => current + event.data.content);
          }
          if (event.event === "error") {
            setOutput((current) =>
              `${current}\n\n[错误] ${event.data.message}`.trim(),
            );
          }
        },
      );
    } catch (reason) {
      const detail = errorText(reason);
      setOutput((current) => `${current}\n\n[错误] ${detail}`.trim());
      void message.error(detail, 6);
    } finally {
      setStreaming(false);
    }
  };

  return (
    <div className="provider-layout">
      <Card title="新增 Provider" className="provider-form-card">
        <Paragraph type="secondary">
          第一版统一使用 OpenAI-compatible 协议。API Key 会加密保存，保存后不再展示明文。
        </Paragraph>
        <ProviderForm
          form={createForm}
          onFinish={create}
          saving={saving}
          submitText="保存 Provider"
        />
      </Card>

      <Card title={`Provider 列表（${providers.length}）`} loading={loading}>
        {!providers.length && !loading ? (
          <Empty description="还没有 Provider，请先创建一个" />
        ) : (
          <List
            dataSource={providers}
            renderItem={(provider) => (
              <List.Item>
                <Card
                  size="small"
                  className="provider-card"
                  title={
                    <Space wrap>
                      <Text strong>{provider.name}</Text>
                      <Tag color={provider.configured ? "success" : "error"}>
                        {provider.configured ? "密钥已配置" : "密钥缺失"}
                      </Tag>
                      {!provider.enabled && <Tag>已停用</Tag>}
                    </Space>
                  }
                  extra={
                    <Switch
                      checked={provider.enabled}
                      onChange={(value) => void toggle(provider, value)}
                    />
                  }
                >
                  <Paragraph copyable className="provider-url">
                    {provider.base_url}
                  </Paragraph>
                  <Space wrap>
                    {provider.models.map((model) => (
                      <Tag key={model.id} color={model.enabled ? "blue" : "default"}>
                        {model.display_name}
                      </Tag>
                    ))}
                  </Space>
                  <div className="provider-actions">
                    <Button onClick={() => openEditor(provider)}>编辑配置</Button>
                    <Button
                      loading={testingId === provider.id}
                      onClick={() => void runConnectionTest(provider)}
                    >
                      测试连接
                    </Button>
                    <Popconfirm
                      title="确定删除 Provider 和它的加密密钥？"
                      onConfirm={() => void remove(provider.id)}
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

      <Card title="流式模型测试" className="stream-card">
        <Space direction="vertical" size="middle" className="full-width">
          <Space wrap>
            <Select
              placeholder="选择 Provider"
              value={selectedProviderId}
              options={providers
                .filter((item) => item.enabled)
                .map((item) => ({ value: item.id, label: item.name }))}
              onChange={(providerId) => {
                const provider = providers.find((item) => item.id === providerId);
                setSelectedProviderId(providerId);
                setSelectedModelId(
                  provider?.models.find((model) => model.enabled)?.id,
                );
              }}
              style={{ minWidth: 220 }}
            />
            <Select
              placeholder="选择模型"
              value={selectedModelId}
              options={(selectedProvider?.models ?? [])
                .filter((item) => item.enabled)
                .map((item) => ({ value: item.id, label: item.display_name }))}
              onChange={setSelectedModelId}
              style={{ minWidth: 220 }}
            />
          </Space>
          <TextArea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            autoSize={{ minRows: 3, maxRows: 8 }}
          />
          <Button
            type="primary"
            loading={streaming}
            disabled={!selectedModelId}
            onClick={() => void runStream()}
          >
            {streaming ? "模型正在逐块返回" : "发送并观察 SSE"}
          </Button>
          <div className="stream-output">
            <Text type="secondary">模型输出</Text>
            <pre>{output || "流式内容会逐步出现在这里。"}</pre>
          </div>
        </Space>
      </Card>

      <Modal
        title={`编辑 ${editing?.name ?? "Provider"}`}
        open={Boolean(editing)}
        onCancel={() => setEditing(null)}
        onOk={() => editForm.submit()}
        confirmLoading={saving}
        destroyOnHidden
      >
        <ProviderForm
          form={editForm}
          onFinish={saveEdit}
          saving={saving}
          hideSubmit
          editing
        />
      </Modal>
    </div>
  );
}

function ProviderForm({
  form,
  onFinish,
  saving,
  submitText,
  hideSubmit = false,
  editing = false,
}: {
  form: ReturnType<typeof Form.useForm<ProviderFormValues>>[0];
  onFinish: (values: ProviderFormValues) => void;
  saving: boolean;
  submitText?: string;
  hideSubmit?: boolean;
  editing?: boolean;
}) {
  return (
    <Form
      form={form}
      layout="vertical"
      onFinish={onFinish}
      initialValues={{
        base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
        models_text: "qwen-plus",
      }}
    >
      <Form.Item
        name="name"
        label="名称"
        rules={[{ required: true, message: "请输入 Provider 名称" }]}
      >
        <Input placeholder="例如：我的 DashScope" />
      </Form.Item>
      <Form.Item
        name="base_url"
        label="Base URL"
        rules={[{ required: true, type: "url", message: "请输入完整 URL" }]}
      >
        <Input placeholder="https://.../v1" />
      </Form.Item>
      <Form.Item
        name="api_key"
        label={editing ? "替换 API Key（留空则不修改）" : "API Key"}
        rules={editing ? [] : [{ required: true, message: "请输入 API Key" }]}
      >
        <Input.Password
          autoComplete="new-password"
          placeholder={editing ? "••••••••" : "sk-..."}
        />
      </Form.Item>
      <Form.Item
        name="models_text"
        label="模型名称"
        extra="每行一个，也可以用逗号分隔"
        rules={[{ required: true, message: "至少配置一个模型" }]}
      >
        <TextArea
          autoSize={{ minRows: 2, maxRows: 6 }}
          placeholder={"qwen-plus\nqwen-max"}
        />
      </Form.Item>
      {!hideSubmit && (
        <Button type="primary" htmlType="submit" loading={saving}>
          {submitText}
        </Button>
      )}
    </Form>
  );
}

function toProviderInput(
  values: ProviderFormValues,
  requireKey: boolean,
): ProviderInput {
  const models = values.models_text
    .split(/[\n,]/)
    .map((name) => name.trim())
    .filter(Boolean)
    .map((model_name) => ({ model_name }));
  const input: ProviderInput = {
    name: values.name.trim(),
    base_url: values.base_url.trim(),
    models,
  };
  if (requireKey || values.api_key?.trim()) {
    input.api_key = values.api_key?.trim();
  }
  return input;
}

function errorText(reason: unknown): string {
  return reason instanceof Error ? reason.message : "发生未知错误";
}
