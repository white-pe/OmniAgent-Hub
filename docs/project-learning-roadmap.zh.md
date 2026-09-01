# PawTeam Lite 完整学习与面试复盘路线

更新时间：2026-09-01

## 1. 我们接下来的目标

从现在开始，项目主线不是部署，而是两件事：

1. 把项目继续完善成一个可信的简历项目；
2. 让石磊能够从业务、架构、代码、数据库、异常处理和取舍六个角度独立讲清它。

代码可以由助手生成，但下面这些能力必须由你掌握：

- 能画出模块之间的关系；
- 能沿着一次请求找到每一层代码；
- 能解释哪些数据存数据库、哪些存文件、哪些只在内存；
- 能说明为什么这样设计，而不是只说“代码就是这样写的”；
- 能说出失败场景和保护措施；
- 能在面试追问时指出当前方案的边界与演进方向。

## 2. 项目的一个总心智模型

```text
配置面
Provider + Secret + Model
        ↓
Agent + Workspace + Skill + Tool 授权
        ↓
Team 编排 / Channel 绑定

运行面
ChatSession
        ↓
Message + AgentRun
        ↓
PromptBuilder + RunManager
        ↓
Provider 流式模型调用
        ↓
ToolCall / Delegation / SSE / ChannelReply

存储面
SQLite：结构化业务事实与审计
data/workspaces：Agent Markdown 与 Skill 正文
data/secrets：加密后的 Provider/Channel Secret
```

以后遇到任何文件，先判断它属于配置面、运行面还是存储面。

## 3. 九个阶段分别回答什么问题

| 阶段 | 核心问题 | 你必须讲清的内容 |
|---|---|---|
| 0 工程地基 | 项目如何启动和分层？ | FastAPI、React、SQLite、Alembic、配置、测试 |
| 1 Provider | 模型从哪里来，密钥怎么保护？ | OpenAI-compatible、Model、SecretStore、连接测试 |
| 2 Agent | 一个 Agent 是什么？ | 数据库配置、Workspace 文件、版本与补偿事务 |
| 3 Blueprint | 如何用几句话创建 Agent？ | 生成草案、Schema 校验、人工确认、一次性应用 |
| 4 Chat Runtime | 一条消息如何执行？ | Session、Message、Run、PromptBuilder、SSE、取消 |
| 5 Skills/Tools | Agent 如何获得能力？ | Skill 注入、Tool 白名单、参数校验、权限和审计 |
| 6 Team | 多 Agent 如何协作？ | Coordinator、成员白名单、父子 Run、循环和深度控制 |
| 7 Channel | 外部消息如何进入系统？ | 企业微信、幂等、外部会话映射、投递审计 |
| 8 安全 | 系统怎样具备运行安全基线？ | 登录、CSRF、生产配置、恢复、健康检查 |
| 9 产品工作台 | 能力怎样被观察和演示？ | 总览、统一会话、审计、按需加载、Markdown 安全 |

## 4. 每个阶段固定使用五步教学法

### 第一步：画业务图

先不看具体代码，只回答：谁发起、谁处理、产生什么数据、失败会怎样。

### 第二步：认文件

只认这一阶段最重要的 5～10 个文件，明确每个文件的职责，避免被整个目录淹没。

### 第三步：走一条真实请求

从前端函数开始，进入 API Route、Service、数据库/文件，再走回响应。必要时在 PyCharm 手工打断点。

### 第四步：查真实数据

用数据库查询、Workspace 文件和页面审计验证刚才的理解。不能只凭代码猜运行结果。

### 第五步：面试反讲

你用自己的话回答三个问题：

1. 这一阶段解决了什么业务问题？
2. 最关键的技术设计是什么？
3. 当前方案有什么限制，下一步怎么演进？

## 5. 横向复盘顺序

阶段 9 完成后，不再机械地从阶段 0 重读一遍，而是按四条业务链横向复盘。

### 链路 A：从几句话到一个 Agent

```text
自然语言描述
  → Blueprint 生成
  → 严格 Schema
  → 草案落库
  → 人工编辑确认
  → Agent 数据库记录
  → Workspace 模板文件
  → Skill / Tool 授权
```

对应阶段：1、2、3、5。

### 链路 B：从一条消息到一个回答

```text
ChatPage
  → Chat API
  → User Message + queued Run
  → PromptBuilder
  → Provider Client
  → SSE delta
  → Assistant Message + completed Run
```

对应阶段：1、2、4、5、9。

### 链路 C：协调 Agent 到成员 Agent

```text
Coordinator
  → delegate_to_agent
  → Team 成员白名单
  → Delegation
  → Child Run
  → 成员独立能力边界
  → 父 Run 汇总
```

对应阶段：5、6、9。

### 链路 D：企业微信到统一会话

```text
企业微信
  → Channel 连接
  → 幂等入站消息
  → ExternalConversation
  → ChatSession / RunManager
  → 回复投递
  → 网页统一审计
```

对应阶段：4、6、7、9。

## 6. 我们会产出的学习成果

后续每一条横向链路都产出：

- 一张业务流程图；
- 一份 10 分钟讲稿；
- 一份 PyCharm 断点清单；
- 一组数据库观察题；
- 5～10 道面试追问；
- 一次由你完成的“反向讲解”。

## 7. 项目完善优先级

### P0：影响正确性或面试可信度

- 关键链路的自动化测试；
- 错误状态和并发保护；
- 审计数据一致性；
- Secret、Workspace 和 Agent 权限边界。

### P1：影响演示和理解

- 工作台信息结构；
- 业务总览与状态可见；
- Chat、Tool、Delegation 可观察；
- 示例数据与一键演示流程；
- 项目文档和架构图。

### P2：扩展能力

- 服务端分页与搜索；
- 使用量、Token、延迟统计；
- 更多 Channel；
- 更复杂的 Workflow/DAG；
- 多用户和权限系统。

我们优先完成 P0 和 P1，不为了显得“大而全”过早引入 P2。

## 8. 面试时的三层回答结构

任何模块都按三层回答：

### 第一层：30 秒

说明业务目标和结果。

### 第二层：2 分钟

讲核心对象、调用链和关键取舍。

### 第三层：追问

讲事务、并发、异常、安全、可观测性、局限和演进。

例如回答 Run：

> 30 秒：我把每次模型执行抽象为独立 Run，实现流式输出、取消、失败恢复和审计。

> 2 分钟：发送消息时先在一个事务中保存 User Message 和 queued Run，再由 RunManager 异步准备 Prompt、Tools 和 Provider 客户端，通过 SSE 推送增量，最后保存 Assistant Message 和终态。

> 追问：同一会话通过活动 Run 唯一约束和服务层检查避免并发；SSE 只负责体验，数据库是最终真相；进程重启会恢复中断 Run。

## 9. 下一步学习安排

阶段 9 验收完成后，先进入第一条横向复盘：

```text
Provider → Agent → PromptBuilder → RunManager → Provider Client
```

目标不是再开发功能，而是让你第一次完整地从模型配置走到一次真实回答。完成后，你应该可以独立回答：

- 为什么 Agent 只存 Provider/Model ID，不存 API Key；
- Prompt 到底由哪几部分组成；
- Workspace 和数据库谁是真相；
- Run 为什么在模型调用前先落库；
- Provider 404 应该在哪一层定位。
