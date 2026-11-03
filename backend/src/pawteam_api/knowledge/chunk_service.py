"""Create and retrieve deterministic chunk sets for parsed versions."""

import hashlib
from uuid import uuid4

from anyio import to_thread
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pawteam_api.knowledge.chunking import (
    KnowledgeTextChunk,
    KnowledgeTextChunker,
)
from pawteam_api.knowledge.documents import (
    KnowledgeDocumentVersionNotFoundError,
)
from pawteam_api.knowledge_schemas import (
    KnowledgeChunkingConfig,
    KnowledgeChunkResponse,
    KnowledgeChunkSetResponse,
)
from pawteam_api.models import (
    KnowledgeChunk,
    KnowledgeChunkSet,
    KnowledgeDocumentParseResult,
    KnowledgeDocumentVersion,
)


class KnowledgeChunkSourceNotReadyError(ValueError):
    """文档版本尚未解析成功，不能执行切块。"""


class KnowledgeChunkingService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        # 使用 Session 工厂，让 Service 独立控制读取会话和写入事务。
        self.session_factory = session_factory

    async def create_chunk_set(
        self,
        document_id: str,
        version_id: str,
        config: KnowledgeChunkingConfig,
    ) -> KnowledgeChunkSetResponse:
        """生成一份切块批次；相同文本与配置会复用已有批次。"""

        async with self.session_factory() as session:
            # 同时检查文档 ID 和版本 ID，确保版本确实属于 URL 中的文档。
            version = await session.scalar(
                select(KnowledgeDocumentVersion).where(
                    KnowledgeDocumentVersion.id == version_id,
                    KnowledgeDocumentVersion.document_id == document_id,
                )
            )
            if version is None:
                raise KnowledgeDocumentVersionNotFoundError(version_id)

            # 只有已解析的版本才能切块。不能绕过解析阶段直接处理源文件。
            if version.status != "parsed":
                raise KnowledgeChunkSourceNotReadyError(
                    f"Document version is not parsed: {version.status}"
                )

            parse_result = await session.get(
                KnowledgeDocumentParseResult,
                version_id,
            )
            if parse_result is None:
                # parsed 状态但解析结果缺失表示数据不一致，不当作空文本处理。
                raise RuntimeError(
                    "Parsed version has no saved parse result"
                )

            source_text = parse_result.text

            # 再检查解析器保存的字符数，尽早暴露不一致的派生数据。
            if parse_result.char_count != len(source_text):
                raise RuntimeError(
                    "Parse result character count does not match its text"
                )

        # 使用规范化文本的 UTF-8 字节计算摘要。
        # 这个摘要不同于上传版本上的原始文件 sha256。
        source_text_sha256 = hashlib.sha256(
            source_text.encode("utf-8")
        ).hexdigest()

        chunker = KnowledgeTextChunker(config)

        # 切块属于同步 CPU 工作。文本量目前受解析阶段限制，
        # 仍将它放到线程中执行，避免阻塞异步事件循环。
        chunks = await to_thread.run_sync(chunker.split, source_text)

        if not chunks:
            # 正常解析文本不应产生空批次；这里作为防御性检查，
            # 避免创建一个无法用于检索的成功批次。
            raise RuntimeError("Chunker produced no chunks")

        try:
            # begin() 保证批次和所有片段同成同败：
            # 块插入失败时，批次记录也会回滚。
            async with self.session_factory.begin() as session:
                # 重新读取解析结果，确认计算期间它仍然存在且未变化。
                current_result = await session.get(
                    KnowledgeDocumentParseResult,
                    version_id,
                )
                if current_result is None:
                    raise KnowledgeChunkSourceNotReadyError(
                        "Parse result is no longer available"
                    )

                current_digest = hashlib.sha256(
                    current_result.text.encode("utf-8")
                ).hexdigest()
                if current_digest != source_text_sha256:
                    raise KnowledgeChunkSourceNotReadyError(
                        "Parse result changed while chunking"
                    )

                existing = await self._find_chunk_set(
                    session=session,
                    version_id=version_id,
                    source_text_sha256=source_text_sha256,
                    config=config,
                )
                if existing is not None:
                    return await self._response(session, existing)

                chunk_set = KnowledgeChunkSet(
                    id=str(uuid4()),
                    version_id=version_id,
                    source_text_sha256=source_text_sha256,
                    splitter_name=chunker.splitter_name,
                    splitter_version=chunker.splitter_version,
                    chunk_size=config.chunk_size,
                    chunk_overlap=config.chunk_overlap,
                )
                session.add(chunk_set)

                # 先插入批次，获得可供子记录引用的 ID。
                await session.flush()

                chunk_records = [
                    self._make_chunk_record(chunk_set.id, chunk)
                    for chunk in chunks
                ]
                session.add_all(chunk_records)

                # 显式 flush，让约束错误在离开事务前出现。
                # 任何一个片段失败都会使整个事务回滚。
                await session.flush()
                await session.refresh(chunk_set)

                # 返回 Pydantic 响应值，而不是让 ORM 对象逃出 Session。
                return await self._response(session, chunk_set)

        except IntegrityError:
            # 两个相同请求可能同时查不到批次，然后竞争插入唯一配置。
            # 失败事务已经由 begin() 回滚；开新会话查找获胜请求的批次。
            async with self.session_factory() as session:
                existing = await self._find_chunk_set(
                    session=session,
                    version_id=version_id,
                    source_text_sha256=source_text_sha256,
                    config=config,
                )
                if existing is not None:
                    return await self._response(session, existing)

            # 如果没有相同配置的批次，IntegrityError 很可能来自其他约束；
            # 不要把真实数据错误伪装成幂等成功。
            raise

    async def _find_chunk_set(
        self,
        session: AsyncSession,
        version_id: str,
        source_text_sha256: str,
        config: KnowledgeChunkingConfig,
    ) -> KnowledgeChunkSet | None:
        """按数据库唯一键查找完全相同的切块配置。"""

        return await session.scalar(
            select(KnowledgeChunkSet).where(
                KnowledgeChunkSet.version_id == version_id,
                KnowledgeChunkSet.source_text_sha256
                == source_text_sha256,
                KnowledgeChunkSet.splitter_name
                == KnowledgeTextChunker.splitter_name,
                KnowledgeChunkSet.splitter_version
                == KnowledgeTextChunker.splitter_version,
                KnowledgeChunkSet.chunk_size == config.chunk_size,
                KnowledgeChunkSet.chunk_overlap == config.chunk_overlap,
            )
        )

    @staticmethod
    def _make_chunk_record(
        chunk_set_id: str,
        chunk: KnowledgeTextChunk,
    ) -> KnowledgeChunk:
        """把算法输出映射为数据库模型，并再次验证来源区间。"""

        if chunk.char_count != len(chunk.text):
            raise ValueError("Chunk character count does not match its text")

        if chunk.end_char - chunk.start_char != chunk.char_count:
            raise ValueError("Chunk offsets do not match its character count")

        return KnowledgeChunk(
            id=str(uuid4()),
            chunk_set_id=chunk_set_id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            char_count=chunk.char_count,
            start_char=chunk.start_char,
            end_char=chunk.end_char,
        )

    async def _response(
        self,
        session: AsyncSession,
        chunk_set: KnowledgeChunkSet,
    ) -> KnowledgeChunkSetResponse:
        """读取该批次的片段，并转换为稳定的 API Schema。"""

        chunks = (
            await session.scalars(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.chunk_set_id == chunk_set.id)
                .order_by(KnowledgeChunk.chunk_index)
            )
        ).all()

        if not chunks:
            # 正常写入流程不会产生空批次。已有空批次说明数据不完整。
            raise RuntimeError("Chunk set has no chunks")

        return KnowledgeChunkSetResponse(
            id=chunk_set.id,
            version_id=chunk_set.version_id,
            source_text_sha256=chunk_set.source_text_sha256,
            splitter_name=chunk_set.splitter_name,
            splitter_version=chunk_set.splitter_version,
            chunk_size=chunk_set.chunk_size,
            chunk_overlap=chunk_set.chunk_overlap,
            created_at=chunk_set.created_at,
            chunks=[
                KnowledgeChunkResponse(
                    id=chunk.id,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    char_count=chunk.char_count,
                    start_char=chunk.start_char,
                    end_char=chunk.end_char,
                )
                for chunk in chunks
            ],
        )