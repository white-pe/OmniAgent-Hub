import { useState } from "react";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Divider,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from "antd";

import {
  applyBlueprint,
  cancelBlueprint,
  generateBlueprint,
  type AgentBlueprint,
  type BlueprintDraft,
  type BlueprintGenerateInput,
} from "../api/blueprints";
import type { Provider } from "../api/providers";

const { Paragraph, Text } = Typography;
const { TextArea } = Input;

const TOOL_OPTIONS = [
  { label: "读取 Workspace 文件", value: "read_workspace_file" },
  { label: "搜索 Workspace 文件", value: "search_workspace_files" },
  { label: "委派给其他 Agent", value: "delegate_to_agent" },
];

interface PreviewFormValues extends AgentBlueprint {
  provider_id: string;
  model_id: string;
}

export default function BlueprintCreator({
  providers,
  onCreated,
}: {
  providers: Provider[];
  onCreated: () => Promise<void>;
}) {
  const [generateForm] = Form.useForm<BlueprintGenerateInput>();
  const [previewForm] = Form.useForm<PreviewFormValues>();
  const [generating, setGenerating] = useState(false);
  const [applying, setApplying] = useState(false);
  const [draft, setDraft] = useState<BlueprintDraft | null>(null);
  const generateProviderId = Form.useWatch("provider_id", generateForm);
  const previewProviderId = Form.useWatch("provider_id", previewForm);
  const requestedTools = Form.useWatch("requested_tools", previewForm) ?? [];
  const isCoordinator = Form.useWatch("is_coordinator", previewForm);
  const generationModels = modelsFor(providers, generateProviderId);
  const previewModels = modelsFor(providers, previewProviderId);

  const generate = async (values: BlueprintGenerateInput) => {
    setGenerating(true);
    try {
      const nextDraft = await generateBlueprint(values);
      setDraft(nextDraft);
      previewForm.setFieldsValue({
        ...nextDraft.blueprint,
        provider_id: nextDraft.source_provider_id,
        model_id: nextDraft.source_model_id,
      });
      void message.success("蓝图草案已生成，请逐项审查后再确认");
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setGenerating(false);
    }
  };

  const apply = async (values: PreviewFormValues) => {
    if (!draft) return;
    setApplying(true);
    const { provider_id, model_id, ...blueprint } = values;
    try {
      const agent = await applyBlueprint({
        draft_id: draft.draft_id,
        blueprint,
        provider_id,
        model_id,
      });
      setDraft(null);
      generateForm.resetFields();
      previewForm.resetFields();
      void message.success(`${agent.name} 与 Blueprint Workspace 已创建`);
      await onCreated();
    } catch (reason) {
      void message.error(errorText(reason));
    } finally {
      setApplying(false);
    }
  };

  const cancel = async () => {
    if (applying) return;
    const currentDraft = draft;
    setDraft(null);
    previewForm.resetFields();
    if (!currentDraft || currentDraft.status !== "draft") return;
    try {
      await cancelBlueprint(currentDraft.draft_id);
      void message.info("草案已取消，没有创建 Agent 或 Workspace");
    } catch (reason) {
      void message.error(errorText(reason));
    }
  };

  return (
    <>
      <Card title="用几句话创建专用 Agent" className="blueprint-card">
        <Paragraph type="secondary">
          模型只生成结构化草案，不会直接创建 Agent。你可以预览并修改角色、目标、规则、
          Tool 请求和模型绑定，确认后才会写入数据库与 Workspace。
        </Paragraph>
        <Form form={generateForm} layout="vertical" onFinish={generate}>
          <Form.Item
            name="description"
            label="你希望这个 Agent 做什么？"
            rules={[
              { required: true, message: "请描述 Agent 用途" },
              { min: 10, message: "请至少输入 10 个字符" },
            ]}
          >
            <TextArea
              autoSize={{ minRows: 4, maxRows: 9 }}
              placeholder="例如：创建一个严格的 FastAPI 代码审查助手，先指出高风险问题，再给修改建议；不确定时要明确说明……"
            />
          </Form.Item>
          <div className="blueprint-model-row">
            <Form.Item
              name="provider_id"
              label="由哪个 Provider 生成草案"
              rules={[{ required: true }]}
            >
              <Select
                options={providers.map((provider) => ({
                  value: provider.id,
                  label: provider.name,
                }))}
                onChange={() => generateForm.setFieldValue("model_id", undefined)}
              />
            </Form.Item>
            <Form.Item
              name="model_id"
              label="生成模型"
              rules={[{ required: true }]}
            >
              <Select options={generationModels} disabled={!generationModels.length} />
            </Form.Item>
          </div>
          <Button
            type="primary"
            htmlType="submit"
            loading={generating}
            disabled={!providers.length}
          >
            生成可编辑 Blueprint 草案
          </Button>
        </Form>
      </Card>

      <Modal
        title="审查 Agent Blueprint"
        open={Boolean(draft)}
        width={980}
        confirmLoading={applying}
        okText="确认并创建 Agent"
        cancelText="取消草案"
        cancelButtonProps={{ disabled: applying }}
        closable={!applying}
        maskClosable={!applying}
        onOk={() => previewForm.submit()}
        onCancel={() => void cancel()}
        destroyOnHidden
      >
        {draft && (
          <>
            <Alert
              type="info"
              showIcon
              title="生成与应用已经分离"
              description={`草案 ${draft.draft_id} 由 ${draft.source_provider_name} / ${draft.source_model_name} 生成。关闭此窗口会取消草案，不产生 Agent。`}
            />
            {draft.warnings.map((warning) => (
              <Alert
                key={warning}
                className="blueprint-warning"
                type="warning"
                showIcon
                title={warning}
              />
            ))}
          </>
        )}
        <Form form={previewForm} layout="vertical" onFinish={apply}>
          <Divider titlePlacement="start">身份与用途</Divider>
          <div className="blueprint-grid">
            <Form.Item name="name" label="名称" rules={[{ required: true }]}>
              <Input maxLength={100} />
            </Form.Item>
            <Form.Item
              name="model_hint"
              label="模型能力偏好（仅建议）"
              rules={[{ required: true }]}
            >
              <Select
                options={[
                  { value: "fast", label: "fast · 速度优先" },
                  { value: "balanced", label: "balanced · 平衡" },
                  { value: "reasoning", label: "reasoning · 推理优先" },
                ]}
              />
            </Form.Item>
          </div>
          <Form.Item name="description" label="用途说明" rules={[{ required: true }]}>
            <TextArea autoSize={{ minRows: 2, maxRows: 5 }} maxLength={1000} />
          </Form.Item>
          <Form.Item name="role" label="专业身份" rules={[{ required: true }]}>
            <TextArea autoSize={{ minRows: 2, maxRows: 4 }} maxLength={500} />
          </Form.Item>
          <Form.Item name="tone" label="沟通风格" rules={[{ required: true }]}>
            <Input maxLength={300} />
          </Form.Item>

          <Divider titlePlacement="start">目标与规则</Divider>
          <StringList name="goals" label="工作目标" />
          <StringList name="rules" label="行为规则" />

          <Divider titlePlacement="start">能力请求与实际模型</Divider>
          <Form.Item name="requested_tools" label="Tool 请求">
            <Checkbox.Group options={TOOL_OPTIONS} />
          </Form.Item>
          {requestedTools.includes("delegate_to_agent") && !isCoordinator && (
            <Alert
              className="blueprint-warning"
              type="error"
              showIcon
              title="只有协调 Agent 才能请求 delegate_to_agent，请勾选协调角色或移除该 Tool。"
            />
          )}
          <Form.Item name="requested_skills" label="Skill 请求">
            <Select
              mode="tags"
              tokenSeparators={[",", " "]}
              placeholder="例如 code-review；本阶段只记录，不会自动安装"
            />
          </Form.Item>
          <Form.Item name="is_coordinator" valuePropName="checked">
            <Checkbox>作为协调 Agent（加入 Team 后可进行受控委派）</Checkbox>
          </Form.Item>
          <div className="blueprint-grid">
            <Form.Item
              name="provider_id"
              label="实际绑定 Provider"
              rules={[{ required: true }]}
            >
              <Select
                options={providers.map((provider) => ({
                  value: provider.id,
                  label: provider.name,
                }))}
                onChange={() => previewForm.setFieldValue("model_id", undefined)}
              />
            </Form.Item>
            <Form.Item
              name="model_id"
              label="实际绑定 Model"
              rules={[{ required: true }]}
            >
              <Select options={previewModels} disabled={!previewModels.length} />
            </Form.Item>
          </div>
          <Space wrap>
            <Text type="secondary">Tool 白名单：</Text>
            {TOOL_OPTIONS.map((tool) => (
              <Tag key={tool.value}>{tool.value}</Tag>
            ))}
          </Space>
        </Form>
      </Modal>
    </>
  );
}

function StringList({
  name,
  label,
}: {
  name: "goals" | "rules";
  label: string;
}) {
  return (
    <Form.List name={name}>
      {(fields, { add, remove }, { errors }) => (
        <Form.Item label={label} required>
          <div className="blueprint-string-list">
            {fields.map((field, index) => (
              <Space key={field.key} align="baseline" className="full-width">
                <Form.Item
                  {...field}
                  noStyle
                  rules={[{ required: true, message: `${label}不能为空` }]}
                >
                  <Input placeholder={`${label} ${index + 1}`} />
                </Form.Item>
                <Button disabled={fields.length === 1} onClick={() => remove(field.name)}>
                  删除
                </Button>
              </Space>
            ))}
            <Button type="dashed" onClick={() => add()}>
              添加一条
            </Button>
            <Form.ErrorList errors={errors} />
          </div>
        </Form.Item>
      )}
    </Form.List>
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
