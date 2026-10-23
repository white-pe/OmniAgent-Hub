# 阶段 9：产品化工作台与面试表达层

更新时间：2026-09-01

## 1. 这一阶段解决什么问题

阶段 0～8 已经让 OmniAgent 具备完整的后端能力，但“功能存在”不等于“产品可讲”。阶段 9 不增加新的 Agent 核心协议，而是把已有能力组织成一套容易操作、容易观察、也容易在面试中解释的产品工作台。

这一阶段完成四件事：

1. 把旧的宣传型首页改成后台工作台；
2. 增加系统总览，将 Provider、Agent、Team、Channel 和 Chat 汇总展示；
3. 强化统一会话控制台，让网页与企业微信历史、Run、Tool 和 Delegation 都能被检索和审计；
4. 将页面按需加载，并安全渲染模型返回的 Markdown。

阶段 9 的核心价值不是“换皮”，而是建立一层面向操作者的可观测性。面试时可以把它概括为：

> 我把一个能运行的多 Agent 后端，整理成了一个可配置、可操作、可追踪、可演示的本地优先工作台。

## 2. 本阶段涉及的文件

```text
frontend/src/
├── App.tsx                    # 应用壳、模块导航、页面标题、按需加载
├── styles.css                # 工作台、总览、会话、Markdown 和响应式样式
├── api/
│   ├── http.ts               # 所有前端请求的公共入口、Cookie、CSRF、401 事件
│   ├── agents.ts             # Agent API 与类型
│   ├── channels.ts           # Channel API 与类型
│   ├── chats.ts              # Chat、Run、ToolCall、Delegation API 与类型
│   ├── health.ts             # 健康检查 API
│   ├── providers.ts          # Provider API 与类型
│   └── teams.ts              # Team API 与类型
└── pages/
    ├── OverviewPage.tsx      # 系统总览
    └── ChatPage.tsx          # 统一会话与执行审计

frontend/package.json         # lucide-react、react-markdown、remark-gfm
```

后端没有为“做一个总览”专门增加聚合接口。`OverviewPage` 复用已有资源接口，这是一种适合当前小型项目的取舍。

## 3. 前端应用是怎样装起来的

### 3.1 启动入口

入口位于 `frontend/src/main.tsx`：

```text
main.tsx
  → React StrictMode
  → AuthGate
  → App
```

`AuthGate` 先调用 `/api/auth/status`：

- 未开启认证：后端直接返回已认证，进入 `App`；
- 开启认证且 Cookie 有效：进入 `App`；
- 未登录或任意 API 返回 401：显示管理员登录页。

因此 `App` 不需要在每个页面重复判断登录状态。认证属于应用外壳的横切关注点，由 `AuthGate` 统一处理。

### 3.2 App 是“壳”，不是业务页面

`frontend/src/App.tsx` 负责：

- 左侧模块导航；
- 当前模块的标题和说明；
- 侧栏收起与小屏幕适配；
- 记住用户上次打开的页面；
- 退出登录；
- 按需加载具体页面。

`pages` 数组是导航配置的单一来源：

```text
key + label + description + icon + content
```

同一份配置同时驱动左侧菜单、顶部标题和页面组件，避免菜单名称改了、标题却忘记同步。

当前页面 key 写入：

```text
localStorage["pawteam_active_page"]
```

它只保存界面偏好，不保存 Token、Provider 密钥或业务数据。

### 3.3 为什么使用 lazy 和 Suspense

每个页面通过 `lazy(() => import(...))` 动态导入。用户首次进入系统总览时，不需要立刻下载 Channel 扫码、Agent 编辑器和 Chat Markdown 渲染等全部代码。

调用关系：

```text
用户点击菜单
  → setPageKey(key)
  → 计算当前 page
  → Suspense 渲染 PageContent
  → 浏览器首次请求该页面对应的 JS chunk
```

优化前，主要前端代码集中在一个约 1.16 MB 的文件中；优化后，Overview、Chat、Agent、Team、Provider、Channel 等页面分别形成独立 chunk。基础依赖仍可能形成较大的共享包，这是 Ant Design 和 React 的公共运行时代码，不是页面业务重复打包。

面试表达：

> 我没有一开始就引入复杂路由系统，而是先用配置驱动的工作台导航；当页面数量增加后，通过 React lazy 和 Suspense 做页面级代码分割，降低首次加载成本，同时保留结构简单的优点。

## 4. 系统总览怎样工作

### 4.1 数据加载

`OverviewPage.refresh()` 使用 `Promise.all` 并行请求：

```text
GET /api/providers
GET /api/agents
GET /api/teams
GET /api/channels
GET /api/chats
GET /api/health
```

选择并行而不是依次等待，是因为这些资源互不依赖。

```text
串行：A 完成 → B 完成 → C 完成 → ...
并行：A、B、C、D、E、F 同时开始 → 等最慢的一项
```

### 4.2 Snapshot 的作用

六个接口的结果被组合成一个 `Snapshot`：

```ts
interface Snapshot {
  agents: Agent[];
  channels: Channel[];
  chats: ChatSession[];
  health: HealthResponse;
  providers: Provider[];
  teams: Team[];
}
```

页面再从 Snapshot 计算：

- 已启用 Provider 数；
- active Agent 数；
- active Team 数；
- active/connected Channel 数；
- 总会话与外部会话数。

这里展示的是“派生状态”，数据库不需要为了首页再存一份计数，否则容易出现计数和真实数据不一致。

### 4.3 为什么暂时不做 `/api/dashboard`

当前项目是单管理员、本地优先的小型系统，资源数量有限，复用六个现有接口能减少后端重复查询和新 DTO。

当系统扩大后，应考虑聚合接口，典型触发条件包括：

- 首页请求数明显影响延迟；
- 需要跨表统计最近 24 小时成功率、Token、费用等；
- 不同接口的权限规则复杂；
- 数据量大，前端不能获取全量再计数。

这是一项刻意保留的扩展点，而不是“不知道可以聚合”。

## 5. 统一会话控制台的状态模型

`ChatPage` 同时处理资源列表、当前会话、后台 Run 和 SSE，因此理解状态分组非常重要。

### 5.1 配置状态

```text
agents       可选 Agent
agentId      当前 Agent 范围；也可以是全部 Agent
```

### 5.2 会话状态

```text
chats        左侧会话摘要列表
chatId       当前选中的会话
detail       当前会话完整详情
query        搜索词
sourceFilter 全部 / 网页 / 企业微信
```

`visibleChats` 使用 `useMemo` 从 `chats` 派生，不再维护第二份会话列表。这样搜索条件变化时重新计算即可，不会发生原始列表与过滤列表不同步。

### 5.3 加载状态为什么拆开

```text
loading         Agent 或会话列表加载
detailLoading   当前会话详情加载
creating        新建会话请求
sending         创建 Run 请求
```

如果所有请求共用一个 `loading`，用户点击某个会话时可能让整个左栏闪烁；拆分后，列表和详情能够独立反馈。

### 5.4 运行时状态

```text
activeRun          当前顶层 Run
liveOutput         SSE 增量文本
liveToolEvents     当前 Run 的 Tool 实时事件
liveDelegations    当前 Run 的委派实时事件
streamState        给用户看的连接/执行状态
eventSourceRef     当前 EventSource 连接
```

这些数据是“运行中的临时视图”。最终状态仍写入数据库，并通过 `getChat()` 重新读取。

## 6. 一条网页消息的完整链路

这是阶段 9 复盘时最重要的一条链路。

### 6.1 前端创建命令

```text
用户点击发送
  → ChatPage.send()
  → createRun(chatId, content)
  → POST /api/chats/{chat_id}/runs
```

### 6.2 Route 只负责 HTTP 边界

`backend/src/pawteam_api/api/routes/chats.py` 中的 `create_run()`：

1. 接收并校验 `RunCreate`；
2. 调用 `RunCommandService.create()`；
3. 把领域异常翻译成 HTTP 409/404；
4. 事务提交成功后调用 `run_manager.start(run.id)`；
5. 立即返回 HTTP 202。

Route 不直接拼 Prompt，也不直接调用模型。

### 6.3 Command Service 先持久化事实

`RunCommandService.create()`：

1. 联查 Chat、Agent、Model；
2. 拒绝归档会话；
3. 拒绝从网页向外部 Channel 会话伪造用户消息；
4. 拒绝停用 Agent；
5. 检查同一会话是否已有活动顶层 Run；
6. 创建 `AgentRun(status="queued")`；
7. 创建 User `Message`；
8. 必要时用首条消息生成会话标题；
9. 在同一事务中提交。

关键设计：先把用户输入和 queued Run 落库，再启动后台任务。如果进程在模型调用前退出，系统仍知道有一个中断的 Run，可以在启动恢复流程中处理。

### 6.4 RunManager 执行

```text
RunManager.start(run_id)
  → 后台 asyncio Task
  → _prepare()
      → 读取 Agent、Provider、Model、Message
      → SecretStore 解密 API Key
      → PromptBuilder 读取 Workspace 与启用 Skill
      → ToolRegistry 提供该 Agent 已授权 Tool
      → Team Runtime 按需提供 delegate_to_agent
  → Provider Client 流式请求模型
  → 保存 delta / ToolCall / Delegation / 终态
  → 发布 SSE 事件
```

### 6.5 前端为什么先 `loadDetail` 再连接 SSE

`send()` 创建 Run 后会：

1. 清空输入框；
2. 重新读取会话详情，让刚落库的 User Message 立即出现；
3. 调用 `connectToRun()` 连接 `/api/runs/{run_id}/events`；
4. 接收 `run.delta`、`tool.*`、`delegation.*` 和终态事件。

当 `run.completed`、`run.failed` 或 `run.cancelled` 到达后，前端清空临时流状态，再次读取详情。最终展示以数据库记录为准。

这是一种“实时事件提升体验，持久化数据保证正确性”的设计。

## 7. 企业微信消息为什么也能在网页看到

企业微信入口和网页入口最终汇聚到同一组核心实体：

```text
企业微信消息
  → WeComBot WebSocket 或加密回调
  → ChannelIngressService
  → ChannelMessage(inbound)
  → ExternalConversation
  → ChatSession(channel="wecom")
  → Message(user)
  → AgentRun
  → RunManager
  → ChannelDispatcher
  → ChannelMessage(outbound)
```

`GET /api/chats` 对 `ChatSession`、`ExternalConversation` 和 `Channel` 做外连接，所以网页列表能拿到：

- Channel 名称；
- Channel 类型；
- 外部会话 ID；
- 外部用户 ID。

网页把外部会话设置为只读，原因不是技术做不到，而是要保持消息来源语义：如果网页可以替企业微信用户继续发言，审计时就无法判断输入真正来自哪里。

## 8. Team 委派为什么能在会话详情看到

协调 Agent 调用动态 Tool `delegate_to_agent` 后：

```text
父 Run
  → Delegation 记录
  → 子 Run(parent_run_id = 父 Run ID, depth + 1)
  → 成员 Agent 独立 Prompt、Workspace、Skill、Tool 权限
  → 子结果写入 Delegation.result_text
  → 返回父模型继续汇总
```

`ChatService.get()` 会先取出该会话的全部 Run ID，再查询：

```text
Delegation.root_run_id IN 当前会话的 Run IDs
```

因此详情中不只显示最近的父 Run，也能还原协调者向成员分发的任务、状态、深度和结果链路。

## 9. Markdown 渲染与安全边界

模型输出天然经常包含：

- 标题；
- 有序/无序列表；
- 行内代码与代码块；
- 引用；
- Markdown 表格。

`ReactMarkdown + remark-gfm` 将这些内容渲染为 React 节点。默认不会把回答中的原始 HTML 当成可信 DOM 执行，本阶段也没有引入 `rehype-raw`。

面试时不要只说“用了 Markdown 库”，要说清安全取舍：

> 模型输出是不可信内容。我允许 Markdown 语义展示，但不开放原始 HTML 注入；这样兼顾可读性和前端安全边界。

## 10. 搜索、筛选和自动刷新

### 搜索

搜索范围包括：

- 会话标题；
- Agent 名称；
- Channel 名称；
- 外部用户 ID。

搜索只处理已加载的会话列表，适合当前数据规模。大规模系统应改为服务端分页与搜索。

### 来源筛选

前端显示“全部 / 网页 / 企业微信”。数据库中的会话入口目前为 `console` 或 `wecom`；智能机器人和自建应用的差异由 `channel_kind` 表示。

### 外部会话轮询

ChatPage 每 4 秒刷新会话摘要。如果当前选中的是外部会话，并且 `updated_at` 变化，则自动刷新详情。

网页 Run 本身使用 SSE，不靠轮询获取生成文本；外部 Channel 由另一个终端产生消息，前端没有同一个 EventSource，因此使用低频轮询发现更新。

## 11. 组件与 API 对应表

| 页面操作 | 前端函数 | HTTP API | 后端核心对象 |
|---|---|---|---|
| 打开系统总览 | `refresh()` | 六个 GET 接口 | 各资源 Service + Health |
| 查看会话列表 | `listChats()` | `GET /api/chats` | `ChatService.list()` |
| 查看完整会话 | `getChat()` | `GET /api/chats/{id}` | `ChatService.get()` |
| 新建网页会话 | `createChat()` | `POST /api/chats` | `ChatService.create()` |
| 发送消息 | `createRun()` | `POST /api/chats/{id}/runs` | `RunCommandService` + `RunManager` |
| 监听实时执行 | `EventSource` | `GET /api/runs/{id}/events` | Run 事件流 |
| 停止生成 | `cancelRun()` | `POST /api/runs/{id}/cancel` | `RunCommandService.request_cancel()` |
| 退出登录 | `logout()` | `POST /api/auth/logout` | `AuthManager` |

## 12. 异常与用户反馈

阶段 9 明确区分：

- 首屏加载：Skeleton；
- 局部加载：Spin 或按钮 loading；
- 没有资源：Empty；
- 配置不满足：Alert；
- 短暂操作结果：message；
- 401：公共 `apiFetch` 派发未授权事件，让 `AuthGate` 接管。

这种设计让错误处理不散落成每个页面各自判断登录状态。

## 13. 你在 PyCharm 中必须亲手走一遍

所有操作由你手工执行。

### 13.1 切换分支并检查状态

```bash
git branch --show-current
git status --short
```

预期分支：

```text
codex/stage-9-product-console
```

### 13.2 启动后端和前端

使用已有运行配置：

1. 运行 `Backend API`；
2. 运行 `Frontend Dev`；
3. 打开 `http://127.0.0.1:5173`。

### 13.3 按顺序观察

1. 系统总览的六组数据分别来自哪个接口；
2. 点击左侧模块，观察顶部标题同步变化；
3. 刷新浏览器，确认仍停留在上次模块；
4. 在 Agent 控制台输入搜索词；
5. 切换网页/企业微信来源；
6. 打开一个有 Tool 或 Delegation 的会话；
7. 观察 Run、ToolCall、Delegation 三种审计记录；
8. 查看包含标题、列表、代码或表格的模型回答；
9. 打开浏览器开发者工具 Network，观察 `/api/chats` 和页面 chunk；
10. 切换到一个从未打开过的模块，观察对应 JS 文件此时才加载。

### 13.4 运行检查

```bash
npm --prefix frontend run check
npm --prefix frontend run build
uv run pytest
uv run alembic current
git diff --check
```

当前验收基线：

```text
TypeScript check：通过
Vite production build：通过
Backend tests：23 passed
Alembic：0008 (head)
```

## 14. 断点教学建议

第一次不要一口气追完整条链路。按下面四个断点观察：

### 断点 A：前端发送

文件：`frontend/src/pages/ChatPage.tsx`

位置：`send()` 中调用 `createRun()` 前。

观察：`chatId`、`content`、`activeRun`。

### 断点 B：Route 接收

文件：`backend/src/pawteam_api/api/routes/chats.py`

位置：`create_run()` 第一行。

观察：`chat_id`、`payload.content`。

### 断点 C：事务落库

文件：`backend/src/pawteam_api/runtime/service.py`

位置：`RunCommandService.create()` 的 `commit()` 前。

观察：`run.status == "queued"`、User Message、sequence。

### 断点 D：运行准备

文件：`backend/src/pawteam_api/runtime/manager.py`

位置：`_prepare()`。

观察：Agent、Provider、Model、Prompt、Tools、Team 能力是如何汇合的。

## 15. 面试高频问题

### Q1：为什么 Run 要单独建表，不能直接请求模型后写 Message？

因为模型调用是长耗时、可取消、可能失败的过程。Run 承担状态机和审计职责，Message 表示对话事实。拆开后可以恢复中断、记录耗时与 Token、展示实时状态，并关联 ToolCall 和 Delegation。

### Q2：为什么 SSE 不直接作为最终数据源？

SSE 可能断线、刷新或丢失客户端状态。它只负责实时体验；最终以数据库中的 Message、Run、ToolCall、Delegation 为准。

### Q3：为什么企业微信会话在网页只读？

为了保证消息来源和审计语义。网页可以观察外部会话，但不能伪造成外部用户继续输入。

### Q4：为什么总览页用多个接口？

当前系统规模小、资源接口已经存在，前端并发组合成本低。规模扩大或统计复杂后再演进为聚合接口，避免过早增加后端 DTO 和缓存一致性成本。

### Q5：如何避免模型输出造成 XSS？

将模型输出视为不可信数据，用 ReactMarkdown 解析受控 Markdown，不启用原始 HTML 渲染，也不把内容写入 `dangerouslySetInnerHTML`。

### Q6：当前前端还有哪些可演进点？

- 使用真正的前端路由，让页面状态进入 URL；
- 服务端分页和搜索会话；
- 为 Overview 增加 Run 成功率、Token 和延迟统计；
- 虚拟化超长消息列表；
- 增加 Error Boundary；
- 增加组件测试和端到端测试；
- 进一步拆分 Ant Design 共享包。

回答演进点时不要把项目说得一无是处。应说明当前约束、现有取舍和什么时候需要升级。

## 16. 简历表达

可使用下面这版：

> 独立设计并实现本地优先的多 Agent 工作台 OmniAgent，支持自然语言生成 Agent Blueprint、Provider 与加密密钥管理、独立 Workspace/Skill/Tool 权限、Team 受控委派、网页与企业微信统一会话、SSE 流式执行及 Run/ToolCall/Delegation 全链路审计；使用 FastAPI、SQLAlchemy、React、TypeScript 和 SQLite，并通过页面级代码分割与安全 Markdown 渲染完善产品化控制台。

如果面试官继续追问，你必须能展开三条主线：

1. 一条消息怎样从前端进入 RunManager；
2. 一个 Agent 的 Prompt 怎样由数据库配置和 Workspace 文件组合；
3. Team 委派怎样做到权限隔离、深度控制和全链路审计。

## 17. 阶段 9 完成标准

- 工作台导航、标题和内容区域统一；
- 系统总览能反映现有资源与健康状态；
- 网页和企业微信会话可统一检索与筛选；
- 外部会话保持只读；
- Run、ToolCall、Delegation 审计可见；
- 模型 Markdown 可读且不开放原始 HTML；
- 页面按需加载；
- TypeScript、生产构建、后端测试和迁移检查通过；
- 你能不看代码画出“网页消息 → RunManager → SSE → 持久化”的链路。
