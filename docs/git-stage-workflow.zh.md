# Git 阶段复盘工作流

## 分支约定

```text
main                         当前最新已验收阶段
codex/stage-0-foundation     阶段 0 工程地基快照
codex/stage-1-provider       阶段 1 Provider 快照
codex/stage-2-agent          阶段 2 Agent 与 Workspace 快照
codex/stage-3-blueprint      阶段 3 自然语言 Blueprint 快照
codex/stage-4-runtime        阶段 4 会话、Run 与 SSE 快照
codex/stage-5-tools-skills   阶段 5 Skills、Tools 与 Tool Calling 快照
codex/stage-6-team           未来阶段 6
```

每个阶段分支代表“完成该阶段后，项目应该是什么样”。下一阶段从上一阶段分支创建，形成线性提交历史。

## 在 PyCharm 中复盘

切换分支前先确认没有未提交的个人修改。然后由你在 PyCharm 右下角 Git 分支菜单中选择目标分支，或在 Terminal 使用：

```bash
git switch codex/stage-0-foundation
git switch codex/stage-1-provider
```

切换后依赖版本可能不同，应执行：

```bash
uv sync
cd frontend && npm install
cd ..
```

不要为了复盘分支而对真实 `data/app.db` 执行 downgrade：阶段 1 已经包含真实 Provider 时，降到 `0001` 会删除 Provider 表。阶段 0 的健康检查可以容忍数据库中存在额外的阶段 1 表，日常代码阅读无需修改数据库。

如果要严格验证阶段 0 的迁移，应在阶段 0 分支使用独立数据库：

```bash
PAWTEAM_DATABASE_URL=sqlite+aiosqlite:///./data/stage0-review.db \
  uv run alembic upgrade head
PAWTEAM_DATABASE_URL=sqlite+aiosqlite:///./data/stage0-review.db \
  uv run alembic current
```

预期独立 review 数据库显示 `0001 (head)`，真实 `app.db` 不受影响。

## 对比阶段

```bash
git log --oneline --graph --decorate --all
git diff codex/stage-0-foundation..codex/stage-1-provider --stat
git diff codex/stage-0-foundation..codex/stage-1-provider
```

推荐先看 `--stat` 理解增加了哪些模块，再按业务流阅读具体 diff。

## 阶段 3 分支来源

完成阶段 2 验收后，从阶段 2 创建阶段 3：

```bash
git switch codex/stage-2-agent
git switch -c codex/stage-3-blueprint
```

阶段开发期间只在新分支修改。验收完成后提交，并让 `main` 快进到新阶段。不要把 API Key、`.env`、`data/`、`.venv` 或 `node_modules` 提交到任何分支。

完成阶段 3 后，阶段 4 从阶段 3 创建：

```bash
git switch codex/stage-3-blueprint
git switch -c codex/stage-4-runtime
```

完成阶段 4 后，阶段 5 从阶段 4 创建：

```bash
git switch codex/stage-4-runtime
git switch -c codex/stage-5-tools-skills
```

完成阶段 5 后，阶段 6 从阶段 5 创建：

```bash
git switch codex/stage-5-tools-skills
git switch -c codex/stage-6-team
```
