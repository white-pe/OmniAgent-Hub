"""Coordinate verified source reading, parsing, and result persistence."""

from anyio import to_thread
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pawteam_api.knowledge.documents import (
    KnowledgeDocumentVersionNotFoundError,
)
from pawteam_api.knowledge.parsers import (
    KnowledgeTextParseError,
    KnowledgeTextParser,
    ParsedKnowledgeText,
)
from pawteam_api.knowledge.storage import (
    KnowledgeFileIntegrityError,
    KnowledgeFileNotFoundError,
    KnowledgeFileReadLimitError,
    LocalKnowledgeFileStore,
)
from pawteam_api.knowledge_schemas import (
    KnowledgeDocumentParseResultResponse,
)
from pawteam_api.models import (
    KnowledgeDocumentParseResult,
    KnowledgeDocumentVersion,
)


class KnowledgeDocumentParsingFailedError(ValueError):
    """预期的读取或解析失败，失败原因已经保存到版本记录。"""


class KnowledgeDocumentParsingConflictError(ValueError):
    """版本当前状态不允许执行解析。"""

class KnowledgeDocumentParseResultNotReadyError(ValueError):
    """版本存在，但还没有可以查询的解析结果。"""


class KnowledgeParsingService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        file_store: LocalKnowledgeFileStore,
        parser: KnowledgeTextParser,
    ) -> None:
        # 解析是一个完整工作流，由它自己管理短会话和事务。
        # 不复用调用方已经开启事务的 Session，避免意外提交其他业务数据。
        self.session_factory = session_factory
        self.file_store = file_store
        self.parser = parser

    async def parse_version(
        self,
        document_id: str,
        version_id: str,
    ) -> KnowledgeDocumentParseResultResponse:
        """解析一个版本，成功结果可以重复获取，失败版本允许重试。"""

        async with self.session_factory() as session:
            version = await self._get_version(
                session,
                document_id,
                version_id,
            )

            if version.status not in {"uploaded", "parse_failed"}:
                return await self._completed_result(session, version)

            # 只提取普通字段，离开会话后不再访问这个 ORM 对象。
            # 源文件元信息在本工作流中保持不可变。
            storage_key = version.storage_key
            expected_size = version.size_bytes
            expected_sha256 = version.sha256
            filename = version.original_filename

        # 文件读取和解析发生在数据库会话关闭之后。
        # 不在等待磁盘操作、解码期间持有数据库写事务。
        parsed: ParsedKnowledgeText | None = None
        failure: Exception | None = None

        try:
            content = await to_thread.run_sync(
                self.file_store.read_verified,
                storage_key,
                expected_size,
                expected_sha256,
            )

            # 工作线程只接触普通字节和字符串，不接触 AsyncSession。
            parsed = await to_thread.run_sync(
                self.parser.parse,
                content,
                filename,
            )
        except (
            KnowledgeTextParseError,
            KnowledgeFileNotFoundError,
            KnowledgeFileIntegrityError,
            KnowledgeFileReadLimitError,
        ) as error:
            # 仅捕获我们已经定义的预期失败。
            # 权限问题、数据库问题、程序缺陷等继续向上抛出。
            failure = error

        # begin() 管理这一段事务：
        # 正常退出时提交，异常退出时回滚。
        async with self.session_factory.begin() as session:
            outcome = await session.execute(
                update(KnowledgeDocumentVersion)
                .where(
                    KnowledgeDocumentVersion.id == version_id,
                    KnowledgeDocumentVersion.document_id == document_id,
                    KnowledgeDocumentVersion.status.in_(
                        ["uploaded", "parse_failed"]
                    ),
                )
                .values(
                    status="parsed" if failure is None else "parse_failed",
                    error_message=(
                        None if failure is None else str(failure)[:500]
                    ),
                    updated_at=func.now(),
                )
            )

            if outcome.rowcount != 1:
                # 处理期间可能已有另一个请求完成解析。
                # 重新读取状态，不能覆盖其他请求已经保存的成功结果。
                current = await self._get_version(
                    session,
                    document_id,
                    version_id,
                )
                return await self._completed_result(session, current)

            if failure is None:
                if parsed is None:
                    raise RuntimeError("Parser returned no result")

                result = KnowledgeDocumentParseResult(
                    version_id=version_id,
                    text=parsed.text,
                    char_count=len(parsed.text),
                    source_format=parsed.source_format,
                    parser_name=parsed.parser_name,
                    parser_version=parsed.parser_version,
                )
                session.add(result)

                # flush 将 INSERT 发给数据库，但尚未提交。
                # 如果插入失败，前面的 parsed 状态更新也会一起回滚。
                await session.flush()
                await session.refresh(result)

                # 先构造普通响应对象，再离开事务。
                # return 真正返回前，事务上下文仍会完成提交；
                # 如果提交失败，调用方收到异常，不会收到成功结果。
                return self._response(result)

        # 必须放在事务块外：
        # 如果在事务里直接 raise，parse_failed 和错误原因也会被回滚。
        raise KnowledgeDocumentParsingFailedError(
            str(failure)
        ) from failure

    async def get_result(
        self,
        document_id: str,
        version_id: str,
    ) -> KnowledgeDocumentParseResultResponse:
        """只查询已经保存的解析结果，不读取源文件或触发解析。"""

        async with self.session_factory() as session:
            # 同时检查文档与版本的归属关系。
            # 不能只根据 version_id 返回结果，忽略 URL 中的文档 ID。
            version = await self._get_version(
                session,
                document_id,
                version_id,
            )

            result = await session.get(
                KnowledgeDocumentParseResult,
                version_id,
            )

            if result is None:
                if version.status == "parsed":
                    # parsed 状态必须有对应结果。
                    # 这里属于数据一致性故障，不能当作“尚未解析”处理。
                    raise RuntimeError(
                        "Parsed version has no saved parse result"
                    )

                raise KnowledgeDocumentParseResultNotReadyError(
                    "Parse result is not available"
                )

            # 查询结果本身，不要求版本永远停留在 parsed 状态。
            # 后续版本进入切块、索引阶段时，解析结果仍然可以读取。
            return self._response(result)

    @staticmethod
    async def _get_version(
        session: AsyncSession,
        document_id: str,
        version_id: str,
    ) -> KnowledgeDocumentVersion:
        """同时校验版本 ID 和所属文档，避免父子资源关系被绕过。"""

        version = await session.scalar(
            select(KnowledgeDocumentVersion).where(
                KnowledgeDocumentVersion.id == version_id,
                KnowledgeDocumentVersion.document_id == document_id,
            )
        )
        if version is None:
            raise KnowledgeDocumentVersionNotFoundError(version_id)

        return version

    async def _completed_result(
        self,
        session: AsyncSession,
        version: KnowledgeDocumentVersion,
    ) -> KnowledgeDocumentParseResultResponse:
        """返回已有成功结果；其他不允许的状态明确拒绝。"""

        if version.status != "parsed":
            raise KnowledgeDocumentParsingConflictError(
                f"Cannot parse version in state: {version.status}"
            )

        result = await session.get(
            KnowledgeDocumentParseResult,
            version.id,
        )

        if result is None:
            # parsed 却没有结果，属于数据一致性问题。
            # 不能伪装成普通解析失败或静默返回空文本。
            raise RuntimeError("Parsed version has no saved parse result")

        return self._response(result)

    @staticmethod
    def _response(
        result: KnowledgeDocumentParseResult,
    ) -> KnowledgeDocumentParseResultResponse:
        return KnowledgeDocumentParseResultResponse(
            version_id=result.version_id,
            text=result.text,
            char_count=result.char_count,
            source_format=result.source_format,
            parser_name=result.parser_name,
            parser_version=result.parser_version,
            created_at=result.created_at,
        )