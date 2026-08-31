# PawTeam Lite

PawTeam Lite 是一个教学型、本地优先的多 Agent 平台。当前完成到**阶段 1：Provider、加密密钥管理与单轮流式模型调用**，Agent、Skill 和 Channel 尚未加入。

## 当前能力

- 阶段 0：FastAPI、React、SQLite、Alembic、测试和 Docker 工程地基；
- Provider 与 Model 分表管理；
- OpenAI-compatible Provider 新增、查询、修改、启停和删除；
- Fernet 加密的文件型 SecretStore，API Key 不写入 SQLite、不通过 GET 回传；
- Provider 连接测试；
- `POST + text/event-stream` 单轮流式模型调用；
- React 可视化配置页和流式输出观察区；
- Provider 生命周期、密钥隔离和 SSE 自动测试。

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

用 PyCharm 打开本目录，解释器选择 `.venv/bin/python`。项目自带三个共享运行配置：

- `Backend API`：FastAPI 开发服务器；
- `Backend Tests`：pytest；
- `Frontend Dev`：Vite 开发服务器。

第一次运行阶段 1 前，在 PyCharm Terminal 执行：

```bash
uv sync
uv run alembic upgrade head
```

然后由你手动运行 `Backend API` 和 `Frontend Dev`。

## Provider 数据流

```text
保存 Provider
  → FastAPI /api/providers
  → ProviderService
  ├── 普通配置和 Model 写入 SQLite
  └── API Key 交给 SecretStore 加密写入 data/secrets

流式测试
  → React POST /api/providers/{id}/chat/stream
  → ProviderService 装配 Provider + Model + API Key
  → OpenAICompatibleClient 调用上游 /chat/completions
  → 上游 SSE 转换为 PawTeam start/delta/done/error 事件
  → React 逐块显示内容
```

普通 Provider 响应只有 `configured: true/false`，没有 `api_key` 或 `api_key_ref`。

## 验证

```bash
make test
make check
make build
uv run alembic current
docker compose config
```

阶段 1 的学习、接口和人工验收步骤见 [docs/stage-1-provider-and-secrets.zh.md](docs/stage-1-provider-and-secrets.zh.md)。
