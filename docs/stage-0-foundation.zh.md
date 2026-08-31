# 阶段 0：全栈工程地基

## 1. 阶段目标

阶段 0 不实现 Agent。它要回答的是：前端、后端、配置、数据库、迁移、测试和部署怎样构成一个可以继续演化的软件系统。

完成阶段 0 后，系统只提供健康检查页，但请求已经真实走过：

```text
React → Vite Proxy → FastAPI Router → SQLAlchemy AsyncEngine → SQLite
```

这条链路是后面 Provider、Agent、Skill 和 Channel 共用的工程地基。

## 2. 三个运行部分

| 部分 | 进程/文件 | 默认地址 | 责任 |
| --- | --- | --- | --- |
| React + Vite | Node.js 进程 | `127.0.0.1:5173` | 页面、状态和 API 调用 |
| FastAPI + Uvicorn | Python 进程 | `127.0.0.1:8000` | API、业务逻辑和数据库访问 |
| SQLite | `data/app.db` | 无端口 | 持久化数据 |

PyCharm 只是启动、编辑和调试工具，不属于运行时架构。关闭 PyCharm 后服务随开发进程停止，但项目代码、数据库和配置仍在磁盘上。

## 3. 工程目录

```text
pawteam-lite/
├── backend/
│   ├── src/pawteam_api/
│   │   ├── main.py          # FastAPI 应用工厂和生命周期
│   │   ├── config.py        # 环境配置
│   │   ├── database.py      # 异步数据库引擎
│   │   ├── models.py        # ORM 元数据
│   │   ├── schemas.py       # API 输出契约
│   │   └── api/             # Router 和 endpoint
│   ├── migrations/          # Alembic 数据库版本
│   └── tests/               # 后端自动测试
├── frontend/
│   ├── src/App.tsx          # React 页面入口
│   ├── src/api/health.ts    # 健康接口客户端
│   └── vite.config.ts       # 开发代理
├── data/                    # 本地运行数据，不进入 Git
├── pyproject.toml           # Python 依赖和工具配置
├── uv.lock                  # Python 精确依赖版本
├── docker-compose.yml       # 容器编排
└── Makefile                 # 常用命令别名
```

## 4. 安装过程

```bash
uv sync
cd frontend && npm install
```

`uv sync` 根据 `pyproject.toml` 和 `uv.lock` 创建 `.venv`。`npm install` 根据 `package.json` 和 `package-lock.json` 创建 `node_modules`。

必须区分：

```text
pyproject.toml/package.json       想要哪些依赖
uv.lock/package-lock.json        实际锁定哪些精确版本
.venv/node_modules               本机安装结果，不提交 Git
```

## 5. 后端启动流程

PyCharm 的 `Backend API` 最终执行：

```bash
python -m uvicorn pawteam_api.main:app \
  --app-dir backend/src --reload --port 8000
```

调用链：

```text
Uvicorn 导入 pawteam_api.main
→ 模块执行 app = create_app()
→ get_settings() 读取默认值、.env 和 PAWTEAM_* 环境变量
→ FastAPI 注册 CORS 和 api_router
→ Uvicorn 启动 lifespan
→ ensure_directories() 创建 data 目录
→ create_database_engine() 创建 AsyncEngine
→ Application startup complete
→ 开始接收 HTTP 请求
```

停止时，`lifespan` 在 `yield` 后执行 `engine.dispose()`，释放数据库连接。

### 为什么使用应用工厂

`create_app(settings)` 允许同一份代码用不同配置创建不同实例：

```text
开发实例 → data/app.db
测试实例 → pytest 临时目录/test.db
Docker 实例 → /app/data/app.db
```

如果配置和数据库引擎都写成无法替换的全局变量，自动测试会污染正式数据。

## 6. 健康请求完整流程

### 6.1 React 发起请求

`App.tsx` 首次渲染后执行 `useEffect()`，调用 `fetchHealth()`：

```typescript
fetch("/api/health")
```

前端维护三个状态：

```text
loading → 是否等待响应
health  → 成功数据
error   → 失败信息
```

### 6.2 Vite 开发代理

浏览器访问的是 `5173`，但 `vite.config.ts` 把 `/api` 转发到 `8000`：

```text
浏览器 GET 127.0.0.1:5173/api/health
→ Vite Proxy
→ GET 127.0.0.1:8000/api/health
```

前端因此不需要写死后端完整地址。生产环境中同一个 `/api` 路径改由 Nginx 转发。

### 6.3 FastAPI 路由组合

顶层 Router 定义 `/api`，Health Router 定义 `/health`：

```text
/api + /health = /api/health
```

以后增加业务模块，只需继续挂载 `/providers`、`/agents` 等子 Router。

### 6.4 SQLAlchemy 检查数据库

Health endpoint 从 `app.state` 获取 AsyncEngine，执行：

```sql
SELECT 1
```

如果返回 `1`，服务和数据库都正常；异常则把状态降级为：

```json
{"status":"degraded","database":"unavailable"}
```

### 6.5 Pydantic 输出契约

`HealthResponse` 规定字段和允许值。它让后端输出、OpenAPI 文档和前端 TypeScript 类型形成明确契约，而不是返回随意字典。

## 7. 配置系统

`Settings` 的来源优先级由 Pydantic Settings 处理，所有环境变量使用 `PAWTEAM_` 前缀：

```text
代码默认值
← .env
← 系统环境变量
```

例如：

```env
PAWTEAM_ENVIRONMENT=development
PAWTEAM_DATABASE_URL=sqlite+aiosqlite:///./data/app.db
```

代码不应散落 `os.getenv()`，否则无法知道配置全集、类型和默认值。

## 8. ORM、Migration 和 SQLite

这三个概念不能混淆：

| 概念 | 回答的问题 |
| --- | --- |
| ORM Model | Python 代码怎样表示表和记录 |
| Alembic Migration | 已存在的数据库怎样从旧结构升级到新结构 |
| SQLite | 表和真实数据最终保存在哪里 |

阶段 0 的 `0001` 迁移创建 `system_metadata`。执行：

```bash
uv run alembic upgrade head
```

才会真正改变数据库。只修改 ORM Model 不会自动升级已有数据库。

## 9. 为什么采用异步数据库

接口和数据库访问使用 `async/await`。它不会让一次 SQL 自身变快，而是让服务在等待数据库、模型或外部 API 时继续处理其他请求。

Agent 平台经常等待模型流、工具和 Channel，因此从地基层保持异步，可以避免后期大面积改造。

## 10. 自动测试流程

健康测试：

```text
pytest 创建 tmp_path
→ 构造 test Settings
→ database_url 指向临时 test.db
→ create_app(test_settings)
→ TestClient 启动 lifespan
→ GET /api/health
→ 断言 HTTP 200 和完整 JSON
→ 测试结束释放资源并清理临时目录
```

测试不要求手工启动后端，也不会访问 `data/app.db`。这是可重复测试的关键。

## 11. 本地开发与 Docker

本地开发：

```text
浏览器 → Vite:5173 → FastAPI:8000 → ./data/app.db
```

Docker：

```text
浏览器 → Nginx:8080
             ├── React 静态文件
             └── /api → backend:8000 → /app/data/app.db
```

Docker Volume `pawteam-data` 让容器重建后数据库仍存在。Docker 没有改变业务逻辑，只改变打包、网络和数据路径。

## 12. 阶段 0 人工实验

1. 同时启动 `Backend API` 和 `Frontend Dev`，确认状态为 `ok`；
2. 停止后端并刷新页面，确认前端进入错误状态；
3. 重启后端，点击“重新检查”，确认恢复；
4. 在浏览器 Network 查看 `/api/health`；
5. 执行 `uv run alembic current`，确认 `0001 (head)`；
6. 执行 `uv run pytest -q`，确认测试独立通过。

## 13. 阶段 0 毕业标准

你应该能脱离文档解释：

1. 为什么前端和后端是两个进程；
2. `/api/health` 经过哪些文件和组件；
3. Vite Proxy 与 CORS 分别解决什么问题；
4. `create_app()` 和 lifespan 的作用；
5. Settings 为什么支持测试和 Docker；
6. ORM、Migration、SQLite 的区别；
7. `async/await` 为后续 Agent 带来什么；
8. 测试为什么不污染开发数据库；
9. 锁文件为什么需要进入 Git；
10. Docker 与本地运行的业务代码为什么相同。
