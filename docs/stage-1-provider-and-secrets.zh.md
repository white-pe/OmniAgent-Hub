# 阶段 1：Provider 与密钥管理

## 1. 本阶段解决什么问题

Agent 不是模型。Agent 会组合人格、记忆、技能和工具，而 Provider 只负责提供模型能力。开始创建 Agent 之前，先建立一条可靠、可替换、不会泄漏密钥的模型调用链。

阶段 1 的边界：

- 支持 OpenAI-compatible 文本聊天端点；
- Provider 与 Model 独立持久化；
- API Key 与普通业务数据分离；
- 支持连接测试和单轮流式输出；
- 暂时不保存会话，不构建 Agent，不调用工具。

## 2. 核心架构

```text
React Provider 页面
  → REST /api/providers
  → Provider Router
  → ProviderService
  ├── SQLAlchemy → providers/provider_models → SQLite
  └── SecretStore → Fernet → data/secrets/*.secret

React 流式测试
  → POST /api/providers/{id}/chat/stream
  → ProviderService.runtime()
  → 组合 Base URL + 解密后的 API Key + Model
  → OpenAICompatibleClient
  → 上游 POST {base_url}/chat/completions
  → OmniAgent SSE: start → delta... → done/error
```

Router 不直接操作数据库，也不直接拼上游 HTTP 请求。ProviderService 负责业务编排，OpenAICompatibleClient 只负责协议转换，SecretStore 只负责密钥。

## 3. Provider 为什么和 Model 分开

Provider 保存服务级配置：名称、协议类型、Base URL、密钥引用和启停状态。Model 保存该服务提供的具体模型名称与能力。

这样一个 Provider 可以只配置一次 API Key，却同时提供 `qwen-plus`、`qwen-max` 等多个模型；未来不同 Agent 可以共享 Provider，但选择不同 Model。

如果把模型名直接写在 Provider 上，一个 Provider 只能对应一个模型；如果把 API Key 写进 Agent，每个 Agent 都会重复保存密钥，轮换和审计都会变得困难。

## 4. 密钥保存边界

数据库 `providers.api_key_ref` 只保存类似 `provider-<uuid>` 的引用。真实 API Key 使用 Fernet 对称加密后写入：

```text
data/secrets/provider-<uuid>.secret
```

本地开发第一次启动会生成：

```text
data/secrets/.master.key
```

目录权限尽量设置为 `700`，密钥和密文文件设置为 `600`。普通查询接口只返回：

```json
{"configured": true}
```

不会返回 `api_key` 或 `api_key_ref`。

这能避免数据库导出、普通日志或前端状态意外暴露明文。需要明确：本地 master key 与密文位于同一数据目录，主要防止误泄漏，不等于云端 KMS。生产环境应通过 `PAWTEAM_SECRET_KEY` 从部署平台的 Secret Manager 注入密钥，并单独备份和轮换。

## 5. 数据库迁移

迁移 `0002` 创建：

```text
providers
  id, name, kind, base_url, api_key_ref, enabled,
  created_at, updated_at

provider_models
  id, provider_id, model_name, display_name,
  capabilities_json, enabled, created_at
```

`provider_models.provider_id` 是外键。同一 Provider 下的 `model_name` 必须唯一。编辑 Provider 时按模型名称合并记录，已有模型保留稳定 ID，避免未来 Agent 的模型引用失效。

## 6. API

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/providers` | 查询 Provider，永不返回密钥 |
| POST | `/api/providers` | 创建 Provider、模型和加密密钥 |
| GET | `/api/providers/{id}` | 查询单个 Provider |
| PUT | `/api/providers/{id}` | 修改配置、模型或轮换密钥 |
| DELETE | `/api/providers/{id}` | 删除 Provider、模型和密文文件 |
| POST | `/api/providers/{id}/test` | 使用指定模型做最小连接测试 |
| POST | `/api/providers/{id}/chat/stream` | 单轮流式 completion |

错误状态约定：

- `404`：Provider 或 Model 不存在；
- `409`：名称冲突、Provider 已停用或密钥缺失；
- `422`：表单格式不合法；
- `502`：上游模型服务连接或鉴权失败。

## 7. SSE 事件

流式接口是 POST 请求，因此前端使用 `fetch()` 读取 `ReadableStream`，而不是只能发 GET 的原生 `EventSource`。

```text
event: start
data: {"provider_id":"...","model_id":"...","model":"qwen-plus"}

event: delta
data: {"content":"你"}

event: delta
data: {"content":"好"}

event: done
data: {"model":"qwen-plus"}
```

上游失败时发送 `error` 事件。API Key 只进入上游请求的 Authorization Header，不能出现在 SSE、异常文本或日志中。

## 8. 关键文件

| 文件 | 责任 |
| --- | --- |
| `models.py` | Provider 与 ProviderModel ORM 定义 |
| `provider_schemas.py` | 创建、修改、响应和聊天输入契约 |
| `providers/service.py` | 数据库与 SecretStore 的业务编排 |
| `providers/client.py` | OpenAI-compatible HTTP/SSE 协议 |
| `security/secret_store.py` | 密钥加密、解密、权限和路径约束 |
| `api/routes/providers.py` | HTTP 状态码和 SSE 输出 |
| `frontend/src/api/providers.ts` | 前端 REST 与 SSE 客户端 |
| `frontend/src/pages/ProvidersPage.tsx` | 可视化配置与模型测试 |

## 9. 由你在 PyCharm 中人工验收

### 第一步：同步依赖和迁移

打开 PyCharm Terminal，在 `OmniAgent-Hub` 根目录执行：

```bash
uv sync
uv run alembic upgrade head
uv run alembic current
```

预期最后一行：

```text
0002 (head)
```

### 第二步：启动两个进程

在顶部运行配置中依次运行：

1. `Backend API`
2. `Frontend Dev`

后端日志应出现 `Application startup complete`，前端应显示 `Local: http://localhost:5173/`。

### 第三步：创建真实 Provider

浏览器打开 `http://127.0.0.1:5173`，在“Provider 与模型”页填写：

- 名称：任意便于识别的名称；
- Base URL：模型平台提供的 OpenAI-compatible `/v1` 地址；
- API Key：平台生成的密钥；
- 模型名称：平台真实支持的模型标识，每行一个。

保存后页面只能显示“密钥已配置”，不能再次看到明文。

### 第四步：验证正确与错误路径

1. 点击“测试连接”，正确配置应显示模型名、延迟和短回复；
2. 在“流式模型测试”输入问题，观察文本逐步出现；
3. 编辑 Provider，故意换成错误 Key；
4. 再次测试，应看到可理解的上游 `401/403` 错误；
5. 换回正确 Key，确认恢复。

错误 Key 实验的意义是证明系统没有把所有错误都伪装成“服务器异常”。

### 第五步：检查密钥没有通过 API 返回

打开 `http://127.0.0.1:8000/docs`，执行 `GET /api/providers`。响应中应该有：

```json
{"configured": true}
```

但不能有：

```text
api_key
api_key_ref
```

### 第六步：运行自动测试

在 PyCharm 运行 `Backend Tests`，或在 Terminal 执行：

```bash
uv run pytest -q
```

预期至少 3 个测试通过。

## 10. 阶段 1 毕业标准

你应该能解释：

1. Provider 和 Model 为什么分表；
2. API Key 从页面提交后分别经过哪些组件；
3. 为什么数据库只存 `api_key_ref`；
4. 本地 Fernet 方案能防什么、不能防什么；
5. ProviderService 和 OpenAICompatibleClient 为什么分开；
6. 为什么 POST 流式请求不用原生 EventSource；
7. `start/delta/done/error` 每个 SSE 事件表达什么；
8. 正确 Key、错误 Key和网络超时分别如何呈现；
9. 为什么编辑模型时要尽量保留 Model ID；
10. 为什么此时仍然只是“模型调用平台”，还不是 Agent。

## 11. 后端启动后新增了什么

阶段 1 没有改变 Uvicorn 的入口，但 lifespan 比阶段 0 多装配了三个对象：

```text
create_database_engine(settings)
→ create_session_factory(engine)
→ SecretStore(settings)
→ provider_client_factory = OpenAICompatibleClient
```

它们放入 `app.state`，表示每个应用实例拥有自己的数据库 Session 工厂、密钥仓库和 Provider 客户端工厂。测试可以把客户端工厂替换为 Fake，而不发送真实网络请求。

## 12. 创建 Provider 的代码级调用链

前端 `ProvidersPage.create()`：

```text
用户提交 Form
→ toProviderInput() 把多行模型文本拆成 models[]
→ createProvider()
→ POST /api/providers
```

后端执行：

```text
ProviderCreate 校验
├── name 去空格
├── Base URL 必须是 http(s)，不能嵌入用户名密码
├── API Key 不能为空
└── 同一 Provider 的 model_name 不能重复

create_provider Router
→ get_database_session() 创建本次请求的 AsyncSession
→ ProviderService.create()
→ 预生成 provider UUID
→ 生成 api_key_ref = provider-<uuid>
→ SecretStore.set() 加密 API Key
→ session.add(Provider + ProviderModel[])
→ session.commit()
→ 重新查询 Provider
→ ProviderResponse(configured=true)
→ React 刷新列表
```

如果数据库因名称重复而提交失败，Service 会 rollback，并删除刚写入的密文文件，避免留下没有数据库引用的孤儿密钥。

## 13. 查询 Provider 的代码级调用链

```text
React listProviders()
→ GET /api/providers
→ ProviderService.list()
→ SELECT providers
→ selectinload(provider_models)
→ SecretStore.exists(api_key_ref)
→ ProviderResponse
```

`selectinload` 避免为每个 Provider 单独发送一次模型查询。响应组装时只根据密文文件是否存在计算 `configured`，不调用 `SecretStore.get()`，因此列表接口根本不会解密 API Key。

## 14. 编辑 Provider 与模型合并

编辑表单把 API Key 留空表示不轮换。后端根据 Pydantic 的 `model_fields_set` 区分“字段没有传”和“字段明确传值”。

模型不能简单全部删除再重建。当前算法：

```text
已有模型按 model_name 建立字典
→ 新表单逐个查找同名模型
   ├── 找到：更新显示名、能力和启停状态，保留 id
   └── 未找到：创建新 Model
→ 删除不再存在的旧模型
→ commit
```

稳定 Model ID 很重要，因为阶段 2 的 Agent 会保存 `model_id`。如果每次编辑都换 ID，Agent 引用会失效。

如果同时修改名称和 API Key，但名称唯一约束失败：

```text
数据库 rollback
→ SecretStore 恢复修改前的 API Key
```

这是 SQLite 事务与文件存储之间的补偿事务。

## 15. 删除 Provider 的调用链

```text
React 二次确认
→ DELETE /api/providers/{id}
→ ProviderService 查询实体
→ ORM cascade 删除 ProviderModel
→ 数据库 commit
→ SecretStore.delete(api_key_ref)
→ HTTP 204
→ React 刷新列表
```

先提交数据库再删除密文，保证数据库失败时密钥不会提前丢失。极端情况下文件删除失败可能留下不可达的孤儿密文，但不会导致数据库引用一个不存在的密钥；生产系统可增加定期孤儿清理任务。

## 16. 测试连接的完整流程

```text
用户点击“测试连接”
→ POST /api/providers/{id}/test {model_id}
→ ProviderService.runtime()
   ├── Provider 必须 enabled
   ├── Model 必须属于该 Provider 且 enabled
   └── SecretStore.get(api_key_ref) 解密 API Key
→ 创建 OpenAICompatibleClient
→ POST {base_url}/chat/completions
   model=<model_name>
   messages=[Reply with OK only]
   stream=false
→ 解析 choices[0].message.content
→ 返回模型名、延迟和回复预览
```

只有实际调用阶段才解密密钥，解密后的值只存在于当前 Python 进程内存和发给上游的 Authorization Header 中。

## 17. SSE 流式调用的完整流程

前端发出 POST：

```text
/api/providers/{id}/chat/stream
{
  model_id,
  prompt,
  system_prompt?,
  temperature
}
```

后端先在数据库 Session 有效期内取得运行时快照：

```text
provider_id, provider_name, base_url, api_key, model_id, model_name
```

随后 `StreamingResponse` 开始发送：

```text
events()
→ start
→ OpenAICompatibleClient.stream()
→ httpx.AsyncClient.stream() 调用上游
→ 按行读取上游 data: {...}
→ 跳过空行和非 data 行
→ 遇到 [DONE] 结束
→ 从 choices[0].delta.content 提取文本
→ 每个文本块转换成 OmniAgent delta
→ done
```

前端不能假设一次 `reader.read()` 恰好得到一个事件。网络分块可能把一个 SSE 事件拆成几段，也可能一次返回多个事件。因此 `providers.ts` 使用 `buffer` 累积字符，以双换行定位完整事件，再交给 `parseSseBlock()`。

## 18. 错误流转与排查矩阵

| 现象 | 状态/事件 | 失败层 | 典型原因 |
| --- | --- | --- | --- |
| 表单立即提示 | `422` | Pydantic | URL、空 Key、重复模型名 |
| Provider 不存在 | `404` | ProviderService | URL 中 ID 错误 |
| Model 不存在 | `404` | ProviderService | model_id 不属于 Provider |
| Provider 停用 | `409` | ProviderService | enabled=false |
| 密钥文件缺失 | `409` | SecretStore | 数据目录损坏或被删除 |
| 上游 `401/403` | `502` 或 SSE error | 模型平台 | API Key 错误或无权限 |
| 上游模型 `404` | `502` 或 SSE error | 模型网关 | model_name 拼错或账号组不支持 |
| 连接超时 | `502` 或 SSE error | httpx/网络 | Base URL、网络、代理或服务异常 |
| 响应结构错误 | `502` 或 SSE error | Provider client | 端点并不真正兼容协议 |

你遇到的：

```text
Model "gp-5.6-terra" is not supported by any configured account in this group
```

说明请求已经到达上游模型网关，但 `model` 技术标识无法映射到当前账号。它不是 OmniAgent Router 的 404，也通常不是 API Key 格式问题。页面中的模型名称会被原样发送，必须填写 Provider 控制台真正支持的模型 ID。

## 19. 自动测试怎样隔离真实模型

测试先创建临时 SQLite 和临时 secrets 目录，再把 `app.state.provider_client_factory` 替换为 `FakeProviderClient`：

```text
真实 ProviderService、数据库、SecretStore、Router、SSE
                         ↓ 只替换这一层
                   FakeProviderClient
```

因此测试验证了我们自己的业务代码，却不会消耗 Token 或要求开发者提供真实密钥。

测试还直接检查：

- API JSON 不含 `api_key/api_key_ref`；
- SQLite 二进制文件不含测试 Key 明文；
- `.secret` 文件不含测试 Key 明文；
- 编辑时同名 Model 保留 ID；
- 流中存在 start、多个 delta 和 done；
- 删除后密文文件消失；
- 重复 Provider 名称得到 409。

## 20. 推荐代码阅读顺序

按一次真实业务请求阅读，不要按目录字母顺序阅读：

```text
frontend/src/pages/ProvidersPage.tsx
→ frontend/src/api/providers.ts
→ api/routes/providers.py
→ provider_schemas.py
→ providers/service.py
→ models.py + security/secret_store.py
→ providers/client.py
→ tests/test_providers.py
```

第一遍只追踪创建 Provider；第二遍追踪连接测试；第三遍追踪 SSE。每次都写出“输入、调用对象、持久化位置、输出、失败分支”。

## 21. 你需要能独立复述的三条主线

### 配置主线

```text
Form → ProviderCreate → ProviderService
→ SQLite 普通配置 + SecretStore 加密 Key
→ ProviderResponse(configured)
```

### 非流式测试主线

```text
provider_id + model_id
→ runtime 装配
→ OpenAI-compatible HTTP 请求
→ 普通 JSON 响应
```

### 流式主线

```text
POST prompt
→ 上游 SSE
→ Client 提取 delta.content
→ OmniAgent SSE
→ 浏览器 ReadableStream buffer
→ React 逐块追加文本
```

当你能解释这三条主线以及每条线的错误处理，才算完全掌握阶段 1。
