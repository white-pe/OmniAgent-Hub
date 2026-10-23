# 阶段 2：Agent CRUD 与独立 Workspace

## 1. 本阶段解决什么问题

阶段 1 只证明“平台能可靠调用模型”。模型本身不是 Agent。Agent 至少还需要稳定身份、用途、启停状态、模型选择和独立运行上下文。

阶段 2 建立：

```text
Agent = SQLite 元数据 + Provider/Model 绑定 + 独立 Workspace
```

本阶段可以手动创建和配置 Agent，但还不执行 Agent 对话。自然语言生成配置属于阶段 3，PromptBuilder 和真实 Runtime 属于后续阶段。

## 2. 为什么数据库和文件要同时存在

适合结构化查询和约束的内容放 SQLite：

```text
id, name, description, status,
provider_id, model_id, is_coordinator,
workspace_path, version, created_at, updated_at
```

适合用户阅读、长文本编辑和未来版本管理的内容放 Markdown：

```text
AGENTS.md
SOUL.md
PROFILE.md
MEMORY.md
```

数据库负责“这个 Agent 是谁、是否启用、选择什么模型”；Workspace 负责“模型运行时应该读取哪些文本上下文”。

不要让同一字段存在两个真相来源。Agent 名称、描述、Provider 和 Model 以数据库为准；`PROFILE.md` 即使提到这些信息，也只是运行时补充内容，不会反向修改数据库。

## 3. 目录结构

创建 Agent 后自动得到：

```text
data/workspaces/
└── <agent-uuid>/
    ├── AGENTS.md
    ├── SOUL.md
    ├── PROFILE.md
    └── MEMORY.md
```

目录名使用后端生成的 UUID，不使用用户输入的 Agent 名称。这样可以避免重名、中文路径、路径穿越和重命名目录的问题。

### 四个文件的职责

| 文件 | 当前职责 | 后续用途 |
| --- | --- | --- |
| `AGENTS.md` | 任务边界、工作流程和约束 | PromptBuilder 的主要操作说明 |
| `SOUL.md` | 角色、人格和行为原则 | System Prompt 的身份部分 |
| `PROFILE.md` | 业务背景、偏好和术语 | 持续运行上下文 |
| `MEMORY.md` | 长期记忆文件边界 | 后续记忆摘要 |

阶段 2 只负责创建、隔离和编辑这些文件，不自动把它们发送给模型。

## 4. 数据库迁移 0003

`0003_create_agents.py` 创建 `agents` 表，并建立两个关键外键：

```text
agents.provider_id → providers.id
agents.model_id    → provider_models.id
```

两者都使用 `ON DELETE RESTRICT`。只要 Agent 仍引用某个 Provider 或 Model，就不能删除它们。

阶段 2 还在 SQLite 每次建立连接时执行：

```sql
PRAGMA foreign_keys=ON;
```

SQLite 默认可能不执行外键约束；只在迁移文件里写 ForeignKey，却不启用 PRAGMA，会得到“看起来有外键、运行时却不保护数据”的假安全。

## 5. 后端启动新增流程

FastAPI lifespan 现在装配：

```text
Settings
→ AsyncEngine
→ AsyncSession factory
→ SecretStore
→ WorkspaceStore
→ Provider client factory
```

`WorkspaceStore(settings)` 将 `PAWTEAM_WORKSPACES_DIR` 解析成绝对根目录，并尽量设置目录权限为 `700`。

API Router 不直接拼路径或写文件。它只调用 AgentService；所有路径约束集中在 WorkspaceStore。

## 6. 创建 Agent 的完整业务流程

前端：

```text
用户填写名称、用途、Provider、Model、协调标记
→ createAgent()
→ POST /api/agents
```

后端：

```text
AgentCreate 校验
→ AgentService._validate_model()
   ├── Provider 必须存在并启用
   ├── Model 必须存在并启用
   └── Model.provider_id 必须等于表单 provider_id
→ 生成 agent UUID
→ WorkspaceStore.prepare()
   ├── 在 workspaces 根目录创建 .staging-* 临时目录
   └── 写入四个模板文件
→ WorkspaceStore.finalize()
   └── os.replace 临时目录为 <agent-uuid>
→ Session.add(Agent)
→ 数据库 commit
→ 查询 Provider/Model 展示名
→ AgentResponse
→ React 刷新列表
```

### 为什么先临时目录再改名

如果直接在最终目录逐个写四个文件，写到第二个时崩溃就会留下半个 Workspace。临时目录准备完整后再使用同一文件系统中的 `os.replace()`，目录切换近似原子。

### 数据库提交失败怎么办

Workspace 已完成但数据库因 Agent 重名提交失败时：

```text
Session rollback
→ 删除 staging 或最终 Workspace
→ 返回 HTTP 409
```

因此正常错误不会留下没有数据库记录的 Workspace。

## 7. 查询 Agent

列表查询一次连接三张表：

```text
agents
JOIN providers
JOIN provider_models
```

响应同时包含：

```text
provider_id + provider_name
model_id + model_name
```

前端不需要为了每张 Agent 卡片再分别查询 Provider 和 Model。

## 8. 编辑元数据与乐观锁

每个 Agent 有整数 `version`，初始为 `1`。前端编辑时提交：

```json
{
  "expected_version": 2,
  "description": "新的用途"
}
```

Service 比较：

```text
数据库当前 version == expected_version
├── 是：保存并 version + 1
└── 否：HTTP 409，提示数据已被其他请求修改
```

这叫乐观锁。它假设冲突不频繁，不长期锁表，而是在提交时检测“我编辑的是否仍是最新版本”。

Workspace 文件保存也共享同一个 Agent version，因此元数据和人格文件的任何修改都会推进统一配置版本。

## 9. Workspace 文件读取

```text
GET /api/agents/{agent_id}/files/SOUL.md
→ 查询 Agent 得到 workspace_path
→ WorkspaceStore 棹查文件名白名单
→ 解析并验证路径仍在 workspaces 根目录内
→ UTF-8 读取
→ 返回 content + agent_version
```

允许的文件名只有：

```text
AGENTS.md, SOUL.md, PROFILE.md, MEMORY.md
```

即使用户在 URL 中请求其他文件，后端也不会把它当成任意磁盘路径。

## 10. Workspace 原子写入

保存文件时：

```text
校验 expected_version
→ 读取旧内容作为补偿备份
→ 在同一 Agent 目录创建临时文件
→ 写入、flush、fsync
→ os.replace 临时文件覆盖目标文件
→ Agent.version + 1
→ 数据库 commit
```

如果数据库提交失败：

```text
数据库 rollback
→ 把旧内容原子写回文件
```

临时文件和目标文件位于同一目录，避免跨文件系统移动失去原子性。

## 11. Workspace 路径安全

WorkspaceStore 同时执行：

1. Agent 目录段只能包含字母、数字、`-` 和 `_`；
2. `Path(value).name` 必须等于输入，拒绝 `/` 和 `..`；
3. `resolve()` 后必须位于配置根目录内部；
4. 只允许四个核心文件名；
5. 根目录本身不能作为删除目标；
6. 目录和文件使用收紧权限。

最后一条“不能删除根目录”非常重要。即使上层代码误把 Workspace 根传给 `purge()`，Store 也必须拒绝，而不是删除所有 Agent。

## 12. Agent 启停

```text
POST /api/agents/{id}/toggle
→ active 与 disabled 互换
→ version + 1
→ commit
```

当前阶段只保存状态。后续 AgentRuntime 在执行前必须拒绝 disabled Agent。

## 13. 删除 Agent 的补偿流程

不能先永久删除 Workspace 再提交数据库，因为数据库失败会留下指向不存在目录的 Agent。

当前流程：

```text
Workspace 原目录
→ 原子改名为 .trash-<uuid>
→ 删除 Agent 数据库记录
→ commit
   ├── 成功：永久清理 trash 目录
   └── 失败：rollback，并把 trash 原子恢复为原目录
```

这是一种跨 SQLite 与文件系统的补偿事务。文件系统和数据库无法共享真正的 ACID 事务，因此需要显式设计失败恢复动作。

## 14. Provider 与 Agent 的关系保护

阶段 2 对阶段 1 增加两条约束：

- Agent 引用 Provider 时，删除 Provider 返回 `409`；
- Agent 引用 Model 时，编辑 Provider 不能移除该 Model。

必须先为 Agent 更换 Model 或删除 Agent，才能删除底层 Provider/Model。

这避免数据库中出现“Agent 指向一个已经不存在的模型”。

## 15. API

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/agents` | Agent 列表 |
| POST | `/api/agents` | 创建 Agent 与 Workspace |
| GET | `/api/agents/{id}` | Agent 详情 |
| PUT | `/api/agents/{id}` | 带版本号修改元数据 |
| POST | `/api/agents/{id}/toggle` | 启停 Agent |
| DELETE | `/api/agents/{id}` | 删除 Agent 与 Workspace |
| GET | `/api/agents/{id}/files/{name}` | 读取核心 Markdown |
| PUT | `/api/agents/{id}/files/{name}` | 原子保存核心 Markdown |

主要错误：

- `404`：Agent 或文件不存在；
- `409`：名称重复、版本冲突、Provider/Model 不匹配、Workspace 状态异常；
- `422`：输入长度或格式不合法。

## 16. 前端业务流程

Agent 页面加载时并行请求：

```text
GET /api/agents
GET /api/providers
```

选择 Provider 后，只展示该 Provider 下已启用的 Model。创建完成后重新加载列表。

Workspace 编辑器：

```text
打开 Agent
→ 默认 GET AGENTS.md
→ 切换 Tab 时读取对应文件
→ TextArea 本地编辑
→ 保存时提交 content + agent_version
→ 成功后更新最新 version
```

文件切换不会把未保存文本自动写入后端。用户必须点击保存，这是阶段 2 明确的交互边界。

## 17. 自动测试覆盖什么

阶段 2 自动测试创建临时数据库、临时 SecretStore 和临时 workspaces：

```text
创建 Provider
→ 创建 Agent A 和 B
→ 验证各自拥有四个文件
→ 编辑 A 的 SOUL.md
→ 验证 B 完全不变
→ 使用过期 version 修改，确认 409
→ 编辑元数据并启停
→ 请求非白名单文件，确认 404
→ 尝试删除正在使用的 Provider，确认 409
→ 尝试移除使用中的 Model，确认 409
→ 重启 FastAPI，确认 Agent 与文件仍存在
→ 删除 Agent，确认 Workspace 消失
→ 删除 Provider 成功
```

另有独立测试确保 `WorkspaceStore.purge(root)` 永远被拒绝。

## 18. 由你在 PyCharm 中人工验收

### 第一步：迁移

```bash
uv sync
uv run alembic upgrade head
uv run alembic current
```

预期：

```text
0003 (head)
```

### 第二步：重启进程

停止旧的 `Backend API` 和 `Frontend Dev`，再由你依次重新运行它们。浏览器应显示 `OmniAgent · STAGE 2`。

### 第三步：创建两个 Agent

使用已有 Provider/Model 创建：

```text
行业研究助手
内容写作助手
```

页面应显示两个不同的 Workspace UUID。

### 第四步：验证隔离

1. 打开研究助手的 `SOUL.md`；
2. 增加一句独特内容并保存；
3. 打开写作助手的 `SOUL.md`；
4. 确认没有出现研究助手的修改。

### 第五步：验证持久化

重启后端并刷新页面。两个 Agent、启停状态、版本号和 Workspace 内容都应保留。

### 第六步：验证关系保护

在 Provider 页面尝试删除被 Agent 使用的 Provider，应看到 `Provider is used by an Agent`，而不是删除成功。

### 第七步：运行测试

```bash
uv run pytest -q
```

预期至少 6 个测试通过。

## 19. 推荐代码阅读顺序

### 创建主线

```text
frontend/src/pages/AgentsPage.tsx
→ frontend/src/api/agents.ts
→ api/routes/agents.py
→ agent_schemas.py
→ agents/service.py create()
→ workspaces/store.py prepare()/finalize()
→ models.py Agent
```

### 文件编辑主线

```text
AgentsPage Workspace Modal
→ updateWorkspaceFile()
→ update_workspace_file Router
→ AgentService.update_file()
→ WorkspaceStore.write()
→ Agent.version commit
```

### 删除主线

```text
AgentsPage 删除确认
→ AgentService.delete()
→ stage_delete()
→ SQLite commit
→ purge() 或 restore_delete()
```

## 20. 阶段 2 毕业标准

你需要能独立解释：

1. Agent 为什么不是简单的一行 Prompt；
2. 哪些字段放 SQLite，哪些内容放 Workspace；
3. 为什么 Workspace 目录使用 UUID；
4. 四个 Markdown 文件分别负责什么；
5. 创建 Agent 怎样避免半成品目录；
6. SQLite 与文件系统为什么需要补偿事务；
7. 乐观锁的 `expected_version` 如何阻止覆盖；
8. Workspace 文件为什么使用临时文件、fsync 和 os.replace；
9. 哪些路径检查防止目录穿越和全量删除；
10. 为什么不能删除被 Agent 使用的 Provider/Model；
11. 为什么编辑 A 的文件不会影响 B；
12. 为什么阶段 2 还不能真正与 Agent 对话。

能完整复述“创建、编辑文件、删除”三条调用链，并能指出每一步失败后的恢复动作，才算完全掌握阶段 2。
