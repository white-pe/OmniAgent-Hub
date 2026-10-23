# 阶段 4：会话、Agent Run 与可重放 SSE

## 1. 本阶段解决什么问题

阶段 3 只完成了 Agent 的“配置生成与确认”。Agent 已经有名称、模型绑定和独立 Workspace，但这些配置还没有真正进入模型请求。

阶段 4 建立第一个完整运行闭环：

```text
选择 Agent
→ 创建持久化会话
→ 发送用户消息
→ 创建后台 Run
→ PromptBuilder 装配人格和历史
→ Provider 流式生成
→ SSE 实时显示
→ 保存终态与 Assistant Message
→ 刷新页面恢复历史
```

本阶段版本为 `0.5.0`，数据库迁移为 `0005`，Git 快照分支为：

```text
codex/stage-4-runtime
```

## 2. 本阶段仍然不做什么

当前 Runtime 只处理文本对话，不执行模型返回的 Tool Call。因此还没有：

- Tool Registry；
- Tool 参数校验和执行循环；
- Skill 加载；
- 多 Agent 委派；
- 微信、企业微信 Channel；
- Token 精确统计；
- 多进程任务队列。

阶段 4 的目标是先把“对话状态、运行状态、流式协议、取消和恢复”做可靠。阶段 5 才在这个闭环中插入 Tool 与 Skill。

## 3. 为什么一次发送不能只是一条 Message

用户看到的是一问一答，但系统至少要区分：

```text
Chat Session：对话容器
Message：用户和助手真正说过的话
Run：一次模型执行的生命周期
Run Event：执行过程中发生的增量事件
```

如果只有 Message，就无法准确表示：

- 回答正在排队还是正在生成；
- 用户是否请求停止；
- Provider 是否失败；
- 页面刷新后如何恢复生成状态；
- 同一回答用了哪个模型；
- 运行耗时是多少；
- 已经生成了一部分但最终取消的回答；
- SSE 断线后从哪里继续。

所以“内容”和“执行”必须分开建模。

## 4. 四个核心概念

### 4.1 Chat Session

Chat Session 表示一个 Agent 的一段连续对话：

```text
一个 Session 只绑定一个 Agent
一个 Agent 可以有多个 Session
```

不同 Agent 不能共享同一个 Session，因为它们的 Workspace、模型和职责不同。

### 4.2 Message

Message 是已经进入对话历史的内容：

```text
role = user | assistant
status = final | partial
sequence = 会话内严格递增序号
```

User Message 在创建 Run 时立即保存。Assistant Message 只在 Run 进入终态时保存。

### 4.3 Run

Run 是一次模型调用：

```text
queued
→ running
→ completed

queued/running
→ cancelling
→ cancelled

queued/running
→ failed
```

Run 保存模型快照、输出缓冲、错误、取消标记、开始/结束时间和耗时。

### 4.4 Run Event

Run Event 是 Run 的可重放事件日志：

```text
run.started
run.delta
run.completed
run.failed
run.cancelled
```

每个事件有严格递增的 `sequence`，同时作为 SSE 的 `id`。

## 5. 数据关系

```text
Agent 1 ── N ChatSession
ChatSession 1 ── N Message
ChatSession 1 ── N Run
Run 1 ── N RunEvent
Run 1 ── 1 User Message
Run 1 ── 0..1 Assistant Message
```

这里“Run 对 Message”的数量是业务语义。数据库通过 `messages.run_id` 建立关联，而 `role` 区分用户输入和助手输出。

## 6. 数据库迁移 0005

迁移文件：

```text
backend/migrations/versions/0005_create_chat_runtime.py
```

新增四张表：

```text
chat_sessions
messages
runs
run_events
```

### `chat_sessions`

| 字段 | 含义 |
| --- | --- |
| `id` | 会话 UUID |
| `agent_id` | 绑定的 Agent |
| `title` | 会话标题，第一条消息会自动生成标题 |
| `channel` | 当前固定为 `console` |
| `status` | `active / archived` |
| `created_at` | 创建时间 |
| `updated_at` | 最近消息或 Run 终态时间 |

### `messages`

| 字段 | 含义 |
| --- | --- |
| `id` | Message UUID |
| `session_id` | 所属会话 |
| `run_id` | 由哪次 Run 产生或触发 |
| `role` | `user / assistant` |
| `content` | 消息正文 |
| `status` | `final / partial` |
| `sequence` | 会话内顺序 |
| `created_at` | 创建时间 |

数据库约束：

```text
UNIQUE(session_id, sequence)
```

它避免同一会话出现两个相同顺序的消息。

### `runs`

| 字段 | 含义 |
| --- | --- |
| `id` | Run UUID |
| `session_id` | 所属会话 |
| `agent_id` | 执行 Agent 快照 |
| `provider_id` | Provider 快照 |
| `model_id` | Model 快照 |
| `model_name` | 便于审计的模型名称快照 |
| `status` | Run 状态机 |
| `output_text` | 当前已经生成的完整文本缓冲 |
| `error_message` | 可安全展示的错误 |
| `cancel_requested` | 是否收到停止请求 |
| `input_tokens/output_tokens` | 预留 Token 统计，当前为 null |
| `duration_ms` | 运行耗时 |
| `created_at/started_at/finished_at` | 生命周期时间 |

### `run_events`

| 字段 | 含义 |
| --- | --- |
| `id` | Event UUID |
| `run_id` | 所属 Run |
| `sequence` | Run 内事件序号 |
| `event_type` | SSE 事件类型 |
| `data_json` | 事件数据 |
| `created_at` | 事件持久化时间 |

数据库约束：

```text
UNIQUE(run_id, sequence)
```

## 7. 为什么一个会话只能同时有一个活动 Run

如果同一个 Session 同时接受两次模型运行，两次回答可能争抢下一个 Message sequence，并且它们看到的历史边界也不一致。

应用层会先查询：

```text
status IN (queued, running, cancelling)
```

但只做“先查询再插入”仍存在并发竞态。两个请求可能同时查到没有活动 Run。

所以数据库增加 SQLite 部分唯一索引：

```sql
CREATE UNIQUE INDEX uq_runs_one_active_per_session
ON runs(session_id)
WHERE status IN ('queued', 'running', 'cancelling');
```

应用层检查负责给出友好错误，数据库索引负责最后的并发一致性。

## 8. 创建会话的流程

接口：

```text
POST /api/chats
```

请求：

```json
{
  "agent_id": "agent-uuid"
}
```

流程：

```text
ChatCreate Schema
→ 查询 Agent
→ Agent 必须存在且 active
→ 创建 channel=console 的 ChatSession
→ title 初始为“新会话”
→ commit
→ ChatSessionResponse
```

第一条用户消息发送后，会取压缩后的前 30 个字符作为标题。

## 9. 一次发送的事务边界

接口：

```text
POST /api/chats/{chat_id}/runs
```

请求：

```json
{
  "content": "请分析这个接口的并发风险"
}
```

同步请求内只做可靠、快速的持久化工作：

```text
校验 Chat 和 Agent
→ 检查没有活动 Run
→ 计算下一个 Message sequence
→ 创建 queued Run
→ 创建 User Message
→ 更新会话标题和 updated_at
→ 一次 commit
→ 返回 HTTP 202
```

随后 Router 调用 `RunManager.start(run_id)`，后台任务才开始调用 Provider。

User Message 和 queued Run 必须一起 commit。如果先存 User Message、再创建 Run 失败，历史里就会出现一条永远没有执行记录的问题。

## 10. 为什么 API 返回 202

`202 Accepted` 表示：

```text
请求已经可靠接收并创建 Run
但模型执行还没有完成
```

如果一直等模型完成才返回普通 JSON：

- 用户看不到流式内容；
- HTTP 请求容易超时；
- 无法独立停止；
- 页面刷新会失去执行句柄。

因此“提交 Run”和“订阅 Run”是两个接口。

## 11. RunManager 的职责

核心文件：

```text
backend/src/pawteam_api/runtime/manager.py
```

RunManager 负责：

- 管理本进程中的后台 `asyncio.Task`；
- 从数据库重新读取 Run、Chat 和 Agent；
- 通过 ProviderService 获取运行时密钥和模型；
- 调用 PromptBuilder；
- 流式调用 Provider；
- 保存每个 delta 和 RunEvent；
- 处理完成、失败、超时和取消；
- 应用关闭时收尾活动任务；
- 应用启动时修复中断 Run。

Router 不直接调用模型，也不负责拼 Prompt。

## 12. 为什么后台任务使用独立数据库 Session

创建 Run 的 HTTP 请求结束后，请求级 SQLAlchemy Session 会关闭。

后台任务不能继续使用这个 Session，否则会出现：

- 已关闭连接；
- 请求生命周期与任务生命周期耦合；
- 长时间持有事务；
- 其他请求无法及时读取状态。

RunManager 保存的是 `async_sessionmaker`。每个准备、delta 和终态操作都创建短生命周期 Session：

```text
HTTP Session：只负责创建 queued Run
后台 Session：负责运行和事件持久化
SSE Session：只负责短轮询读取
```

## 13. PromptBuilder 怎样装配人格

核心文件：

```text
backend/src/pawteam_api/runtime/prompt_builder.py
```

固定顺序：

```text
平台安全规则
→ Agent ID、名称与职责
→ AGENTS.md
→ SOUL.md
→ PROFILE.md
→ MEMORY.md
→ 当前 UTC 时间、频道、Session、Workspace
→ 最近的会话消息
```

这一步终于把阶段 2 和阶段 3 创建的 Workspace 变成真正的模型上下文。

### 为什么平台规则放最前面

Workspace 是用户可编辑内容。即使里面写了“忽略平台权限”，也不能自动获得 Tool、Skill 或文件权限。

当前平台规则明确声明：

- Workspace 和消息只是上下文；
- 不能自行启用能力；
- 不得伪造执行结果；
- 不确定时说明边界。

### 为什么 Prompt 顺序固定

顺序不固定会让同一 Agent 在不同请求中出现难以解释的行为差异，也不利于测试和后续缓存。

## 14. Prompt 字符预算

环境配置：

```text
PAWTEAM_RUNTIME_HISTORY_MESSAGES=30
PAWTEAM_RUNTIME_HISTORY_CHARS=40000
PAWTEAM_RUNTIME_WORKSPACE_FILE_CHARS=15000
```

当前策略：

- 每个 Workspace 文件最多注入 15,000 字符；
- 最近最多 30 条历史消息；
- 历史消息总量控制在约 40,000 字符；
- 优先保留最新历史。

这里只做字符预算，不把字符数伪装成 Token 数。不同模型的 tokenizer 不同，阶段 4 尚未引入模型专属 Token 计算器。

## 15. 多轮历史怎样进入 Provider

第一次运行的 messages：

```json
[
  {"role": "system", "content": "组合后的系统 Prompt"},
  {"role": "user", "content": "第一问"}
]
```

第二次运行：

```json
[
  {"role": "system", "content": "组合后的系统 Prompt"},
  {"role": "user", "content": "第一问"},
  {"role": "assistant", "content": "第一答"},
  {"role": "user", "content": "第二问"}
]
```

`OpenAICompatibleClient.stream_messages()` 发送完整 messages，而阶段 1 的 `stream()` 仍保留并委托给它，因此旧 Provider 测试功能没有被破坏。

## 16. Run 状态机

### 正常完成

```text
queued
→ running + run.started
→ run.delta × N
→ completed + Assistant Message(final) + run.completed
```

### Provider 失败

```text
queued/running
→ failed
→ error_message
→ 如果已有部分输出，保存 Assistant Message(partial)
→ run.failed
```

### 超时

整个 Run 使用：

```text
PAWTEAM_RUN_TIMEOUT_SECONDS=120
```

超过后进入 `failed`，错误为 `Agent Run timed out`。

### 用户取消

```text
queued/running
→ cancelling + cancel_requested=true
→ 取消 asyncio Task
→ cancelled
→ 保存已有部分输出
→ run.cancelled
```

## 17. 为什么要保留 `output_text`

每收到一个 Provider delta，系统同时做两件事：

```text
run.output_text += delta
INSERT run.delta event
```

`output_text` 是当前完整快照，Run 查询不需要重新拼所有事件。

`run_events` 是变化日志，用于 SSE 重放和审计。

两者不是含义相同的双真相：

- `output_text` 回答“现在完整输出是什么”；
- `run_events` 回答“输出如何按顺序产生”。

## 18. SSE 事件格式

接口：

```text
GET /api/runs/{run_id}/events
```

示例：

```text
id: 1
event: run.started
data: {"run_id":"...","model":"qwen-plus"}

id: 2
event: run.delta
data: {"run_id":"...","content":"你"}

id: 3
event: run.delta
data: {"run_id":"...","content":"好"}

id: 4
event: run.completed
data: {"run_id":"...","status":"completed","duration_ms":812}
```

SSE 是单向协议，适合“服务端不断向浏览器发送运行事件”的场景，复杂度低于 WebSocket。

## 19. 为什么事件要先入库再发给浏览器

如果 delta 只写入内存队列：

- 页面刷新后无法恢复；
- SSE 断线期间的内容丢失；
- 运行完成后无法重放；
- 多个观察者看不到一致序列。

当前实现采用数据库轮询：

```text
后台任务写 run_events
→ SSE 每 0.15 秒查询 sequence > cursor
→ 按 sequence 输出
→ Run 终态且事件已发完后关闭连接
```

本地教学项目的吞吐量很小，数据库轮询换来了简单、可解释和跨连接恢复。高并发版本可替换为 Redis Streams 或消息队列，但 API 事件语义可以保持不变。

## 20. Last-Event-ID 与重放

SSE 事件带 `id`。浏览器自动重连时会发送：

```text
Last-Event-ID: 3
```

后端从：

```text
sequence > 3
```

继续发送。

接口也支持：

```text
GET /api/runs/{id}/events?after=3
```

页面刷新后创建新的 EventSource 时会从 0 重放，前端重新构造当前流式气泡；完成后的 Assistant Message 则来自持久化历史。

## 21. 浏览器断开为什么不自动取消 Run

本阶段选择：

```text
SSE 断线 ≠ Run 取消
```

理由：

- 用户刷新页面不应浪费已经开始的生成；
- 移动网络短暂断开后应该重连；
- Run 是服务端业务实体，不属于某一个 TCP 连接；
- 用户想停止时应通过显式取消接口表达。

真正停止必须调用：

```text
POST /api/runs/{run_id}/cancel
```

## 22. 取消竞态怎样处理

最危险的情况是：

```text
Run 已创建为 queued
→ 后台 asyncio Task 已登记但还没真正进入函数
→ 用户立即点击停止
```

如果只调用 `task.cancel()`，协程可能在进入 `try/except` 前就被取消，数据库会永久停在 `cancelling`。

当前实现：

```text
task.cancel()
→ await task 收尾
→ 再执行一次幂等 _finish_cancelled()
```

无论任务是否真正开始，都能进入 `cancelled`。终态方法发现 Run 已经终态时会直接返回，所以重复收尾不会创建重复消息或事件。

## 23. 部分回答为什么要保存

如果模型已经生成：

```text
这是初步分析……
```

用户随后点击停止，直接丢弃这些文本会让界面、Run 快照和历史不一致。

当前策略：

```text
run.output_text 保留
Assistant Message.status = partial
前端显示“部分回答”标签
```

下一轮模型也会看到这条 partial Assistant Message，因为它确实是会话中已经展示给用户的内容。

## 24. 应用关闭和重启怎样收尾

### 正常关闭

FastAPI lifespan 在关闭时调用：

```text
RunManager.shutdown()
```

它取消当前任务并等待任务把 Run 写成 `cancelled`，然后才释放数据库 Engine。

### 异常崩溃后重启

进程直接崩溃时没有机会执行 shutdown。下次启动会扫描：

```text
queued / running / cancelling
```

处理规则：

- 已请求取消的 Run → `cancelled`；
- 其他中断 Run → `failed`；
- 已有输出 → 保存 partial Assistant Message；
- 写入对应终态事件。

系统不会假装一次中断的模型请求已经成功。

## 25. Agent 删除为什么现在可能返回 409

`chat_sessions.agent_id` 使用 `ON DELETE RESTRICT`。

Agent 有聊天历史后，直接删除它会让历史失去人格和来源。当前选择保留审计链，所以 Agent 删除返回：

```text
409 Agent has chat history and cannot be deleted
```

AgentService 仍会先把 Workspace 移到临时 trash；数据库拒绝删除后，它 rollback 并把 Workspace 原子恢复到原位置。

未来可以增加“归档 Agent”和“明确清空全部历史后删除”，但不能静默级联删除用户对话。

## 26. API 清单

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/chats` | 创建会话 |
| GET | `/api/chats?agent_id=...` | 查询某 Agent 的会话 |
| GET | `/api/chats/{id}` | 恢复消息和 Run 历史 |
| POST | `/api/chats/{id}/runs` | 保存用户消息并创建 Run |
| GET | `/api/runs/{id}` | 查询 Run 快照 |
| GET | `/api/runs/{id}/events` | 订阅或重放 SSE |
| POST | `/api/runs/{id}/cancel` | 显式停止 Run |

## 27. 前端控制台的状态分工

核心页面：

```text
frontend/src/pages/ChatPage.tsx
```

主要状态：

```text
agents       可选的 active Agent
agentId      当前 Agent
chats        当前 Agent 的会话列表
chatId       当前会话
detail       数据库恢复的消息与 Run
activeRun    当前运行句柄
liveOutput   SSE delta 临时拼接结果
streamState  连接和运行提示
```

`detail.messages` 是数据库历史，`liveOutput` 是当前 SSE 展示缓冲。Run 结束后清空 `liveOutput`，重新获取 detail，让最终 Assistant Message 成为唯一历史来源。

## 28. 前端发送流程

```text
用户输入
→ POST createRun
→ 立即刷新 ChatDetail，显示 User Message
→ EventSource(/runs/{id}/events)
→ run.delta 追加 liveOutput
→ completed/cancelled/failed
→ 关闭 EventSource
→ 重新加载 ChatDetail
→ 显示持久化 Assistant Message 和 Run 审计
```

同一会话存在活动 Run 时，输入框和发送按钮禁用，只保留停止按钮。

## 29. 页面刷新恢复流程

```text
重新加载 Agent 列表
→ 查询该 Agent 的 Chats
→ GET ChatDetail
→ 找到最后一个 queued/running/cancelling Run
→ 重新连接 EventSource
→ 重放已有事件并继续接收新事件
```

如果 Run 已经结束，页面直接显示数据库中的 Assistant Message，不需要 SSE。

## 30. Run 审计区域

控制台底部显示最近四次 Run：

```text
Run ID 前缀
status
model_name
duration_ms
```

这让用户可以区分“聊天内容”和“模型执行记录”。后续 Tool Call、Token 和委派时间线会继续挂在 Run 上。

## 31. 错误如何呈现

| 场景 | Run 状态或 HTTP |
| --- | --- |
| Chat/Run 不存在 | 404 |
| Agent disabled | 409 |
| 同会话已有活动 Run | 409 |
| Provider/Model disabled | Run failed |
| API Key 不存在 | Run failed |
| Provider 返回 4xx/5xx | Run failed，保存安全错误 |
| 整体超时 | Run failed |
| 用户停止 | Run cancelled |

模型调用发生在 HTTP 202 返回之后，因此 Provider 错误主要通过 `run.failed` SSE 和 Run 查询体现，而不是让创建 Run 的请求等待并返回 502。

## 32. 新增和修改的核心文件

### 数据与 Schema

```text
backend/src/pawteam_api/models.py
backend/src/pawteam_api/chat_schemas.py
backend/migrations/versions/0005_create_chat_runtime.py
```

### Runtime

```text
backend/src/pawteam_api/runtime/prompt_builder.py
backend/src/pawteam_api/runtime/service.py
backend/src/pawteam_api/runtime/manager.py
backend/src/pawteam_api/providers/client.py
```

### API

```text
backend/src/pawteam_api/api/routes/chats.py
backend/src/pawteam_api/api/routes/runs.py
backend/src/pawteam_api/api/router.py
backend/src/pawteam_api/main.py
```

### 前端

```text
frontend/src/api/chats.ts
frontend/src/pages/ChatPage.tsx
frontend/src/App.tsx
frontend/src/styles.css
```

### 测试

```text
backend/tests/test_runtime.py
```

## 33. 推荐代码阅读顺序

### 创建会话

1. `ChatPage.addChat()`；
2. `createChat()`；
3. `routes/chats.py:create_chat()`；
4. `ChatService.create()`；
5. `ChatSession` ORM。

### 发送和执行

1. `ChatPage.send()`；
2. `createRun()`；
3. `routes/chats.py:create_run()`；
4. `RunCommandService.create()`；
5. `RunManager.start()`；
6. `RunManager._execute()`；
7. `_prepare()`；
8. `PromptBuilder.build()`；
9. `OpenAICompatibleClient.stream_messages()`；
10. `_append_delta()`；
11. `_finish_terminal()`。

### SSE

1. `ChatPage.connectToRun()`；
2. 浏览器 `EventSource`；
3. `routes/runs.py:stream_run_events()`；
4. `run_events` 查询；
5. `encode_sse()`；
6. 前端各类 `addEventListener()`。

### 取消

1. `ChatPage.stop()`；
2. `cancelRun()`；
3. `RunCommandService.request_cancel()`；
4. `RunManager.cancel()`；
5. `_finish_cancelled()`；
6. partial Assistant Message。

## 34. 自动测试覆盖什么

当前后端共有 11 个测试。

Runtime 测试使用假的 Provider Client，不访问网络、不消耗 Token。

### 多轮与人格隔离

验证：

- Research Agent 和 Writing Agent 分别读取自己的 system prompt；
- 两个 Agent 得到不同回答；
- 第二轮 Provider messages 包含第一轮 user/assistant；
- 消息顺序是 user、assistant、user、assistant；
- 完成消息全部为 final。

### SSE 重放

在 Run 已完成后重新请求事件接口，仍能读到：

```text
run.started
run.delta
run.completed
```

### 历史恢复

关闭第一个 FastAPI 应用并创建新应用后，ChatDetail 仍能读取原消息。

### 取消

假的慢速 Provider 先返回“部分回答”，随后一直等待。测试验证：

- 同会话第二个 Run 被 409 拒绝；
- cancel 后 Run 进入 cancelled；
- 部分文本保留；
- Assistant Message.status 为 partial；
- SSE 包含 run.cancelled。

### 删除保护

有 Chat 的 Agent 删除返回 409，Workspace 被恢复。

## 35. 迁移验收

已验证全新数据库：

```text
0001 → 0002 → 0003 → 0004 → 0005 (head)
```

已验证现有数据库：

```text
0004 → 0005
```

原有 Provider、Blueprint、Agent 和 Workspace 保持不变，新增 Chat/Message/Run/Event 表为空。

## 36. 你在 PyCharm 中怎样体验

所有 PyCharm 操作继续由你手工完成。

### 第一步：同步并确认迁移

在 PyCharm Terminal：

```bash
cd /Users/whitexp/code/AgentProject/OmniAgent-Hub
uv sync
uv run alembic upgrade head
uv run alembic current
```

预期：

```text
0005 (head)
```

然后：

```bash
cd frontend
npm install
cd ..
```

### 第二步：重启服务

由你停止旧的：

```text
Backend API
Frontend Dev
```

再依次重新运行。页面顶部应显示：

```text
OmniAgent · STAGE 4
```

### 第三步：验证人格隔离

在“Agent 控制台”选择行业研究助手，新建会话并发送：

```text
请先介绍你的职责和工作原则，再给我一个你最适合处理的任务示例。
```

切换到内容写作助手，新建另一个会话，发送完全相同的问题。

比较回答是否体现两个 Workspace 的不同角色。

### 第四步：验证多轮

在同一会话继续发送：

```text
请结合你上一轮的回答，把第二点展开。
```

如果模型能引用上一轮内容，说明 Message 历史已进入 Provider messages。

### 第五步：验证刷新恢复

回答过程中或回答完成后刷新浏览器：

- 已完成消息应该仍在；
- 未完成 Run 应重新连接 SSE；
- Run 审计仍显示模型和状态。

### 第六步：验证停止

发送一个明显需要长回答的问题：

```text
请分十个部分详细分析未来五年软件工程师职业发展的变化，每部分给出原因和建议。
```

看到文字开始输出后点击“停止生成”。预期：

- 状态进入 cancelled；
- 已有文本保留并显示“部分回答”；
- 可以继续发送下一轮消息。

## 37. 使用 SQLite 观察运行过程

查看会话：

```bash
sqlite3 -header -column data/app.db \
  "SELECT id, agent_id, title, channel, status, updated_at FROM chat_sessions ORDER BY updated_at DESC;"
```

查看消息顺序：

```bash
sqlite3 -header -column data/app.db \
  "SELECT session_id, sequence, role, status, substr(content,1,60) AS content FROM messages ORDER BY session_id, sequence;"
```

查看 Run：

```bash
sqlite3 -header -column data/app.db \
  "SELECT id, session_id, model_name, status, duration_ms, cancel_requested FROM runs ORDER BY created_at DESC;"
```

查看事件：

```bash
sqlite3 -header -column data/app.db \
  "SELECT run_id, sequence, event_type, data_json FROM run_events ORDER BY run_id, sequence;"
```

不要手工修改 Run 状态，否则会绕过终态消息和事件收尾。

## 38. 本阶段必须完全掌握什么

### 业务概念

你应能解释：

1. Session、Message、Run、Event 为什么必须分开；
2. User Message 为什么和 queued Run 一起提交；
3. Assistant Message 为什么在终态才写入；
4. partial Message 代表什么；
5. 为什么一个 Session 只能有一个活动 Run。

### Runtime

你应能复述：

```text
HTTP 创建 Run
→ 后台 Task
→ 独立 Session
→ PromptBuilder
→ ProviderService.runtime
→ stream_messages
→ delta 持久化
→ terminal 收尾
```

### Prompt

你应能解释：

1. 平台规则为什么在 Workspace 之前；
2. 四个 Markdown 怎样进入 system prompt；
3. 历史为什么限制数量和字符；
4. 为什么字符数不等于 Token；
5. 为什么两个 Agent 的 Prompt 不会混用。

### SSE

你应能解释：

1. `event / data / id` 分别是什么；
2. 为什么 Event 要持久化；
3. `Last-Event-ID` 如何续传；
4. 为什么断开 SSE 不取消 Run；
5. 终态后为什么 SSE 可以关闭。

### 失败与恢复

你应能解释：

1. Provider 失败为什么不会让 Run 永远 running；
2. 取消竞态怎样避免 stuck cancelling；
3. 应用重启怎样处理 orphan Run；
4. 为什么有聊天历史的 Agent 禁止删除；
5. Workspace 在删除失败后怎样恢复。

## 39. 常见误区

### 误区一：SSE 就是 Run

SSE 只是观察 Run 的一种输出通道。Run 即使没有浏览器连接也应继续存在并进入终态。

### 误区二：流式文本只放前端内存

这会导致刷新、断线和审计全部失效。

### 误区三：取消就是关闭 EventSource

关闭 EventSource 只是不再观察，后台模型仍可能继续运行并产生费用。必须调用 cancel API。

### 误区四：把所有历史无限发送给模型

这会持续增加成本并最终超过上下文窗口。当前有明确预算，后续还可以增加摘要。

### 误区五：后台任务继续使用请求 Session

请求结束后 Session 应关闭；后台运行必须有自己的数据库生命周期。

### 误区六：Run failed 就删除 User Message

用户确实发送了这条消息，失败也属于可审计历史。应保留 User Message 和失败 Run。

## 40. 当前限制和阶段 5 接口

当前 Runtime 收到 Provider 的 `tool_calls` delta 时不会执行，只处理文本 content。如果模型只返回 Tool Call 而没有正文，Run 会以“Provider returned no response content”失败。

阶段 5 将在 `_execute()` 中加入：

```text
模型返回 tool_calls
→ ToolRegistry 白名单
→ Pydantic 参数二次校验
→ Tool 执行和超时
→ 记录 ToolCall
→ Tool result 加回 messages
→ 再次调用模型
→ max_steps 防无限循环
```

Skill 则由 PromptBuilder 在构造 system prompt 时按 Agent 配置加载。

## 41. 简历与面试表达

可以写成：

> 实现可恢复的异步 Agent Runtime，将 Session、Message、Run 与 RunEvent 分层建模；通过后台 asyncio Task、独立数据库会话、持久化 SSE 序列和 Last-Event-ID 支持多轮历史、断线重放与显式取消，并用状态机、部分唯一索引和启动恢复机制保证 Run 必达终态。

面试时重点说明：

- 为什么不是一个同步 `/chat` 接口；
- 为什么 Message 和 Run 分开；
- 为什么事件先持久化再推送；
- 取消和断线为什么不是一回事；
- 如何处理并发发送、进程重启和部分回答；
- PromptBuilder 如何隔离不同 Agent 的人格。

## 42. 阶段 4 毕业标准

当你能不看代码回答以下问题，就算掌握阶段 4：

1. 点击发送后，哪两条记录在同一事务创建；
2. HTTP 202 返回后是谁继续执行模型；
3. Run 从 queued 到 completed 经过哪些持久化动作；
4. 第二轮历史从哪里读取并按什么顺序发送；
5. 两个 Agent 为什么会得到不同 system prompt；
6. 每个 delta 同时写入哪两个地方；
7. SSE 断线、页面刷新、用户取消分别发生什么；
8. partial Assistant Message 在什么情况下产生；
9. 同会话并发 Run 在应用层和数据库层如何阻止；
10. 应用崩溃重启后 running Run 如何收尾；
11. 为什么有历史的 Agent 不能直接删除；
12. 阶段 5 会在 Runtime 哪个位置插入 Tool 循环。

能够完整复述“创建会话、发送、后台执行、SSE、终态、刷新恢复、取消”七条链路，并能指出每条链路的数据库状态变化，才算真正掌握阶段 4。
