# OmniAgent

OmniAgent 是一个教学型、本地优先的多 Agent 平台。当前已完成 **阶段 9：产品化工作台与面试表达层**，项目重点转向本地完善、完整复盘与面试演示。

项目工作目录为 `/Users/whitexp/code/AgentProject/OmniAgent-Hub`，后续开发、运行和验证均在此目录执行。

为兼容已有配置和数据，后端 Python 模块名 `pawteam_api`、环境变量前缀 `PAWTEAM_`、Cookie、浏览器存储键和 Docker 数据卷名称保持兼容。

## 当前能力

- 阶段 0：FastAPI、React、SQLite、Alembic、测试和 Docker 工程地基；
- 阶段 1：Provider/Model、Fernet SecretStore、连接测试与 SSE 流式调用；
- 阶段 2：Agent CRUD、Provider/Model 绑定和独立 Markdown Workspace；
- 阶段 3：自然语言生成严格 Blueprint、人工预览编辑、白名单校验和确认创建；
- 阶段 4：多轮 Session/Message、后台 Run、PromptBuilder、SSE 和停止生成；
- 阶段 5：Workspace Skills、逐 Agent Tool 授权、受控调用循环和完整审计；
- 阶段 6：Team 成员白名单、协调 Agent、父子 Run 和受控 Agent 委派；
- 阶段 7：企业微信加密回调、外部会话映射、主动回复和投递审计；
- 阶段 7.1：企业微信智能机器人扫码授权、WebSocket 长连接、断线重连与无公网回调接入；
- 阶段 7.2：网页与企业微信统一会话列表、来源元数据、自动刷新和外部会话只读审计；
- 阶段 8：单管理员登录、CSRF、生产配置校验、Caddy HTTPS、健康检查、备份恢复与 CI；
- 阶段 9：产品化工作台、系统总览、统一会话检索、页面级代码分割和安全 Markdown 渲染；
- `AGENTS.md / SOUL.md / PROFILE.md / MEMORY.md` 可视化编辑；
- Agent 启停、协调 Agent 标记和配置版本控制；
- 数据库与文件操作的补偿事务；
- Workspace 路径白名单、原子写入与 Agent 间隔离；
- Provider/Model 被 Agent 引用时的删除保护；
- Blueprint 草案的取消、过期、一次性应用和来源追踪；
- Blueprint 确认后以确定性模板生成 `AGENTS.md / SOUL.md / PROFILE.md`；
- 控制台会话历史持久化、刷新恢复、Run 状态审计和部分回答保留。
- Tool 参数二次校验、Workspace 路径隔离、超时、结果截断和越权拒绝。
- 委派深度、调用预算、祖先环路阻断、子 Agent 权限隔离和委派审计。

- 企业微信文本消息可绑定普通 Agent 或 Team 协调 Agent。

## 本地启动

要求：Python 3.11～3.14、uv、Node.js 22+。

```bash
cd /Users/whitexp/code/AgentProject/OmniAgent-Hub
cp .env.example .env
make setup
make migrate
```

打开两个终端：

```bash
make dev-backend
make dev-frontend
```

访问：

- 前端：<http://127.0.0.1:5173>
- OpenAPI：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/health>

## PyCharm

用 PyCharm 打开本目录，解释器选择 `.venv/bin/python`。共享运行配置：

- `Backend API`：FastAPI 开发服务器；
- `Backend Tests`：pytest；
- `Frontend Dev`：Vite 开发服务器。

进入阶段 8 后，在 PyCharm Terminal 执行：

```bash
uv sync
uv run alembic upgrade head
uv run alembic current
```

预期数据库版本为 `0008 (head)`。然后由你手动运行 `Backend API` 和 `Frontend Dev`。

在“Blueprint 与 Agent”页输入至少 10 个字符的用途描述，选择生成模型。生成只会保存草案；检查并编辑预览后点击“确认并创建 Agent”，才会创建数据库记录和 Workspace。点击取消不会创建 Agent。

在“Agent 控制台”选择已启用 Agent，新建会话并发送消息。每次发送都会创建一条 User Message 和一个后台 Run；模型增量通过 SSE 展示，终态写入 Assistant Message。刷新页面不会丢失历史，点击停止会保存部分回答并将 Run 标记为 `cancelled`。

在 Agent 卡片点击“配置 Skills / Tools”：Skill 正文保存到该 Agent 的 Workspace，启用后注入系统 Prompt；Tool 来自服务端白名单并默认关闭。授权后，支持 Tool Calling 的 OpenAI-compatible Model 可以在同一 Run 内请求工具，执行结果会回送模型，控制台同时显示实时事件和持久化审计。

在“Team 与委派”页选择一个已标记为协调者的 Agent，并添加至少一个成员。Team 启用后，Runtime 会只向该协调 Agent 提供动态 `delegate_to_agent` Tool。成员任务使用独立子 Run 执行，子 Agent 不继承协调者的 Workspace、Skill 或 Tool 权限，最终结果才回到父 Run 汇总。

在“企业微信 Channel”页优先选择目标 Agent 后扫码授权。后端会取得 Bot ID 与 Secret、加密保存 Secret，并通过企业微信智能机器人 WebSocket 建立长连接，不需要公网 HTTPS。扫码接口异常时可手工填写 Bot ID 与 Secret；原有自建应用回调方案保留在“高级模式”中。

企业微信产生的会话会进入“Agent 控制台”的统一会话列表，默认范围是“全部 Agent / 全部 Channel”。列表和详情会展示入口、Channel 名称、外部用户及完整消息、Run、Tool、委派审计。外部会话在网页中是只读镜像，继续对话应回到原 Channel，避免网页伪造外部用户输入。

## Agent 数据边界

```text
SQLite
  → Agent 名称、描述、状态、Provider/Model 关联、版本和 Workspace 路径

data/workspaces/<agent-id>/
  → AGENTS.md：工作指南与任务边界
  → SOUL.md：角色、人格与行为原则
  → PROFILE.md：运行时背景与偏好
  → MEMORY.md：长期记忆文件边界
  → skills/<skill-name>/SKILL.md：该 Agent 的可启停工作方法

SQLite
  → Skill 元数据、AgentTool 授权、ToolCall 参数/状态/结果审计
  → Team、成员角色、父子 Run 和 Delegation 全链路审计
  → Channel、外部会话映射、inbound/outbound 消息和投递状态

data/secrets/channel_<channel-id>.secret
  → Fernet 加密后的智能机器人 Secret，或自建应用 Token、EncodingAESKey 和 Secret
```

Agent 名称、描述、Provider 和 Model 以 SQLite 为唯一真相；Markdown 由 Runtime 的 PromptBuilder 装载为模型上下文。

## 验证

```bash
make test
make check
make build
uv run alembic current
docker compose config
```

生产环境使用独立编排：

```bash
cp .env.production.example .env.production
# 填写域名和三个生产秘密后
make prod-config
make prod-up
```

生产版仅开放 Caddy 的 80/443，由 Caddy 自动管理 HTTPS；Frontend 与 Backend 保持在 Compose 内网。完整的域名、密钥、备份、恢复和更新流程见阶段 8 文档。

阶段文档：

- [阶段 0：工程地基](docs/stage-0-foundation.zh.md)
- [阶段 1：Provider 与密钥](docs/stage-1-provider-and-secrets.zh.md)
- [阶段 2：Agent 与 Workspace](docs/stage-2-agent-and-workspace.zh.md)
- [阶段 3：自然语言 Blueprint](docs/stage-3-natural-language-blueprint.zh.md)
- [阶段 4：会话、Run 与 SSE](docs/stage-4-chat-runtime-and-sse.zh.md)
- [阶段 5：Skills、Tools 与 Tool Calling](docs/stage-5-tools-and-skills.zh.md)
- [阶段 6：Team 与受控 Agent 委派](docs/stage-6-team-and-delegation.zh.md)
- [阶段 7：企业微信 Channel](docs/stage-7-wecom-channel.zh.md)
- [阶段 7.1：企业微信智能机器人扫码与长连接](docs/stage-7.1-wecom-bot-qr.zh.md)
- [阶段 7.2：跨 Channel 统一会话控制台](docs/stage-7.2-unified-channel-chat.zh.md)
- [阶段 8：生产安全与单机上线](docs/stage-8-production-deployment.zh.md)
- [阶段 9：产品化工作台与面试表达层](docs/stage-9-product-console.zh.md)
- [完整学习与面试复盘路线](docs/project-learning-roadmap.zh.md)
- [Git 阶段复盘](docs/git-stage-workflow.zh.md)
