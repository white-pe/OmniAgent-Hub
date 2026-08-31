# PawTeam Lite

PawTeam Lite 是一个教学型、本地优先的多 Agent 平台。当前只完成**阶段 0：工程骨架**，还没有接入模型、Agent 或企业微信。

## 阶段 0 已包含

- FastAPI 应用工厂与 `/api/health`；
- SQLAlchemy 异步引擎与 SQLite；
- Alembic 初始迁移；
- pytest 健康检查测试；
- React + TypeScript + Vite + Ant Design 健康页；
- Docker Compose；
- 可共享的 PyCharm 运行配置。

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
- 后端健康检查：<http://127.0.0.1:8000/api/health>
- OpenAPI：<http://127.0.0.1:8000/docs>

## PyCharm

用 PyCharm 打开本目录。将项目解释器设置为 `.venv/bin/python`。项目自带三个共享运行配置：

- `Backend API`：FastAPI 开发服务器；
- `Backend Tests`：pytest；
- `Frontend Dev`：Vite 开发服务器。

第一次运行前仍需执行 `make setup && make migrate`。

## 验证

```bash
make test
make check
make build
docker compose config
```

## 一次请求经过哪些层

```text
浏览器
  → Vite 开发代理 /api
  → FastAPI Router
  → health endpoint
  → SQLAlchemy AsyncEngine
  → SQLite SELECT 1
  → Pydantic HealthResponse
  → React 页面
```

完整学习与人工验收步骤见 [docs/stage-0-foundation.zh.md](docs/stage-0-foundation.zh.md)。阶段 1 会在这个骨架上增加 Provider、SecretStore 和真实模型流式调用。
