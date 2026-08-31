"""Path-safe, atomic storage for per-Agent Markdown Workspaces."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

from pawteam_api.config import Settings

CORE_WORKSPACE_FILES = ("AGENTS.md", "SOUL.md", "PROFILE.md", "MEMORY.md")


class WorkspaceError(RuntimeError):
    pass


class WorkspaceFileNotAllowedError(ValueError):
    pass


class WorkspaceStore:
    def __init__(self, settings: Settings) -> None:
        self.root = settings.workspaces_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._harden_permissions(self.root, 0o700)

    def prepare(
        self,
        agent_id: str,
        name: str,
        description: str,
        files: Mapping[str, str] | None = None,
    ) -> Path:
        self._validate_segment(agent_id)
        contents = (
            dict(files) if files is not None else self._templates(name, description)
        )
        if set(contents) != set(CORE_WORKSPACE_FILES):
            raise WorkspaceError("Workspace must contain exactly the four core files")
        if any(len(content) > 200_000 for content in contents.values()):
            raise WorkspaceError("Workspace file content is too large")
        staging = Path(tempfile.mkdtemp(prefix=f".staging-{agent_id}-", dir=self.root))
        self._harden_permissions(staging, 0o700)
        try:
            for filename, content in contents.items():
                path = staging / filename
                path.write_text(content, encoding="utf-8")
                self._harden_permissions(path, 0o600)
        except Exception:
            self.purge(staging)
            raise
        return staging

    def finalize(self, staging: Path, agent_id: str) -> str:
        self._assert_inside_root(staging)
        destination = self._workspace(agent_id)
        if destination.exists():
            raise WorkspaceError("Agent Workspace already exists")
        os.replace(staging, destination)
        return destination.name

    def read(self, workspace_path: str, filename: str) -> str:
        return self._file(workspace_path, filename).read_text(encoding="utf-8")

    def write(self, workspace_path: str, filename: str, content: str) -> str:
        destination = self._file(workspace_path, filename)
        previous_content = destination.read_text(encoding="utf-8")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{filename}.", suffix=".tmp", dir=destination.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            self._harden_permissions(temporary, 0o600)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return previous_content

    def stage_delete(self, workspace_path: str) -> tuple[Path, Path]:
        original = self._workspace(workspace_path)
        if not original.is_dir():
            raise WorkspaceError("Agent Workspace does not exist")
        trashed = self.root / f".trash-{uuid4()}"
        os.replace(original, trashed)
        return original, trashed

    def restore_delete(self, original: Path, trashed: Path) -> None:
        self._assert_inside_root(original)
        self._assert_inside_root(trashed)
        if trashed.exists() and not original.exists():
            os.replace(trashed, original)

    def purge(self, path: Path) -> None:
        self._assert_inside_root(path)
        if path.exists():
            shutil.rmtree(path)

    def _workspace(self, relative_path: str) -> Path:
        self._validate_segment(relative_path)
        path = (self.root / relative_path).resolve()
        self._assert_inside_root(path)
        return path

    def _file(self, workspace_path: str, filename: str) -> Path:
        if filename not in CORE_WORKSPACE_FILES:
            raise WorkspaceFileNotAllowedError(filename)
        workspace = self._workspace(workspace_path)
        path = (workspace / filename).resolve()
        self._assert_inside_root(path)
        if not path.is_file():
            raise WorkspaceError(f"Workspace file {filename} does not exist")
        return path

    def _assert_inside_root(self, path: Path) -> None:
        resolved = path.resolve()
        if resolved == self.root:
            raise WorkspaceError("Workspace root cannot be used as an item path")
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceError("Workspace path escapes its configured root") from exc

    @staticmethod
    def _validate_segment(value: str) -> None:
        valid = value and all(
            character.isalnum() or character in "-_" for character in value
        )
        if not valid or Path(value).name != value:
            raise WorkspaceError("Invalid Workspace path segment")

    @staticmethod
    def _templates(name: str, description: str) -> dict[str, str]:
        purpose = description or "尚未填写用途说明。"
        return {
            "AGENTS.md": (
                f"# {name} 的工作指南\n\n"
                "## 任务边界\n\n"
                f"{purpose}\n\n"
                "## 工作原则\n\n"
                "- 先确认目标和约束，再开始执行。\n"
                "- 对不确定信息明确说明，不编造事实。\n"
                "- 当前阶段尚未启用 Tool 和 Skill。\n"
            ),
            "SOUL.md": (
                f"# {name} 的角色设定\n\n"
                f"你是 {name}。你的主要用途是：{purpose}\n\n"
                "保持清晰、可靠、可解释的沟通方式。\n"
            ),
            "PROFILE.md": (
                "# 运行时补充信息\n\n"
                "在这里记录该 Agent 需要持续参考的背景、偏好和术语。\n\n"
                "> Agent 名称、描述、Provider 和 Model 以数据库记录为准。\n"
            ),
            "MEMORY.md": (
                "# 长期记忆\n\n当前阶段只建立文件边界，自动记忆将在后续阶段实现。\n"
            ),
        }

    @staticmethod
    def _harden_permissions(path: Path, mode: int) -> None:
        if os.name == "posix":
            path.chmod(mode)
