# PawTeam Lite

PawTeam Lite 是一个教学型、本地优先的多 Agent 平台。当前完成到**阶段 3：自然语言 Agent Blueprint**。

## 当前能力

- 阶段 0：FastAPI、React、SQLite、Alembic、测试和 Docker 工程地基；
- 阶段 1：Provider/Model、Fernet SecretStore、连接测试与 SSE 流式调用；
- 阶段 2：Agent CRUD、Provider/Model 绑定和独立 Markdown Workspace；
- 阶段 3：自然语言生成严格 Blueprint、人工预览编辑、白名单校验和确认创建；
- `AGENTS.md / SOUL.md / PROFILE.md / MEMORY.md` 可视化编辑；
- Agent 启停、协调 Agent 标记和配置版本控制；
- 数据库与文件操作的补偿事务；
- Workspace 路径白名单、原子写入与 Agent 间隔离；
- Provider/Model 被 Agent 引用时的删除保护；
- Blueprint 草案的取消、过期、一次性应用和来源追踪；
- Blueprint 确认后以确定性模板生成 `AGENTS.md / SOUL.md / PROFILE.md`。

真实 Agent Runtime、Skill、Tool、Team 和 Channel 将在后续阶段加入。

## 本地启动

要求：Python 3.11～3.14、uv、Node.js 22+。

```bash
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

进入阶段 3 后，在 PyCharm Terminal 执行：

```bash
uv sync
uv run alembic upgrade head
uv run alembic current
```

预期数据库版本为 `0004 (head)`。然后由你手动运行 `Backend API` 和 `Frontend Dev`。

在“Blueprint 与 Agent”页输入至少 10 个字符的用途描述，选择生成模型。生成只会保存草案；检查并编辑预览后点击“确认并创建 Agent”，才会创建数据库记录和 Workspace。点击取消不会创建 Agent。

## Agent 数据边界

```text
SQLite
  → Agent 名称、描述、状态、Provider/Model 关联、版本和 Workspace 路径

data/workspaces/<agent-id>/
  → AGENTS.md：工作指南与任务边界
  → SOUL.md：角色、人格与行为原则
  → PROFILE.md：运行时背景与偏好
  → MEMORY.md：长期记忆文件边界
```

Agent 名称、描述、Provider 和 Model 以 SQLite 为唯一真相；Markdown 是未来 PromptBuilder 装载的运行时内容。

## 验证

```bash
make test
make check
make build
uv run alembic current
docker compose config
```

阶段文档：

- [阶段 0：工程地基](docs/stage-0-foundation.zh.md)
- [阶段 1：Provider 与密钥](docs/stage-1-provider-and-secrets.zh.md)
- [阶段 2：Agent 与 Workspace](docs/stage-2-agent-and-workspace.zh.md)
- [阶段 3：自然语言 Blueprint](docs/stage-3-natural-language-blueprint.zh.md)
- [Git 阶段复盘](docs/git-stage-workflow.zh.md)
