"""管理索引任务记录；实际向量写入仍由 indexing 模块负责。"""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pawteam_api.models import (
    KnowledgeChunkSet,
    KnowledgeEmbeddingProfile,
    KnowledgeVectorIndex,
)
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select, update

from pawteam_api.models import KnowledgeChunk

class VectorIndexLeaseLostError(RuntimeError):
    """执行者已失去租约，或者完成结果不满足任务约束。"""

class VectorIndexBusyError(RuntimeError):
    """任务仍被其他执行者持有，当前请求不能重复领取。"""

class KnowledgeVectorIndexStateService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.session_factory = session_factory

    async def ensure_pending(
        self, *, profile_id: str, chunk_set_id: str,
    ) -> bool:
        """首次创建返回 True；记录已存在返回 False，不重置状态。"""

        # 在访问数据库前验证并规范化 UUID，联合主键顺序与模型一致。
        key = (str(UUID(profile_id)), str(UUID(chunk_set_id)))
        try:
            async with self.session_factory.begin() as session:
                if await session.get(KnowledgeVectorIndex, key) is not None:
                    return False

                # 先检查父资源，提供明确错误，避免仅暴露底层外键异常。
                for model, identity in (
                    (KnowledgeEmbeddingProfile, key[0]),
                    (KnowledgeChunkSet, key[1]),
                ):
                    if await session.get(model, identity) is None:
                        raise LookupError(f"{model.__name__} not found")

                session.add(KnowledgeVectorIndex(
                    profile_id=key[0], chunk_set_id=key[1], status="pending",
                ))
                await session.flush()
            return True
        except IntegrityError:
            # 失败事务退出后已回滚，用新 Session 检查并发请求是否已创建。
            async with self.session_factory() as session:
                if await session.get(KnowledgeVectorIndex, key) is not None:
                    return False
            # 没有对应记录，说明不能解释为重复创建，保留真实错误。
            raise


    async def claim(
        self, *, profile_id: str, chunk_set_id: str, lease_seconds: int = 60,
    ) -> int | None:
        """领取成功返回执行序号；已完成返回 None；正在执行则报错。"""

        if type(lease_seconds) is not int or not 10 <= lease_seconds <= 600:
            raise ValueError("Lease seconds must be between 10 and 600")
        profile_id, chunk_set_id = str(UUID(profile_id)), str(UUID(chunk_set_id))
        await self.ensure_pending(profile_id=profile_id, chunk_set_id=chunk_set_id)

        async with self.session_factory.begin() as session:
            count = await session.scalar(
                select(func.count()).select_from(KnowledgeChunk)
                .where(KnowledgeChunk.chunk_set_id == chunk_set_id)
            )
            if not count:
                raise ValueError("Cannot index an empty chunk set")

            now = datetime.now(UTC)
            # 判断状态和修改状态放在同一条 UPDATE 中，避免先查后改的竞争。
            attempt = await session.scalar(
                update(KnowledgeVectorIndex).where(
                    KnowledgeVectorIndex.profile_id == profile_id,
                    KnowledgeVectorIndex.chunk_set_id == chunk_set_id,
                    or_(
                        KnowledgeVectorIndex.status.in_(("pending", "failed")),
                        and_(
                            KnowledgeVectorIndex.status == "indexing",
                            or_(KnowledgeVectorIndex.lease_until.is_(None),
                                KnowledgeVectorIndex.lease_until <= now),
                        ),
                    ),
                ).values(
                    status="indexing", attempts=KnowledgeVectorIndex.attempts + 1,
                    expected_points=count, indexed_points=0,
                    last_error=None, indexed_at=None, updated_at=now,
                    lease_until=now + timedelta(seconds=lease_seconds),
                ).returning(KnowledgeVectorIndex.attempts)
                .execution_options(synchronize_session=False)
            )
            if attempt is not None:
                return attempt

            # UPDATE 未命中时，区分已经完成与正在被其他执行者处理。
            record = await session.get(
                KnowledgeVectorIndex, (profile_id, chunk_set_id)
            )
            if record is not None and record.status == "indexed":
                return None
            raise VectorIndexBusyError("Index task is already being processed")


    async def renew(
        self,
        *,
        profile_id: str,
        chunk_set_id: str,
        attempt: int,
        lease_seconds: int = 60,
    ) -> None:
        """仅当前执行者可以延长仍然有效的租约。"""

        if type(attempt) is not int or attempt < 1:
            raise ValueError("Invalid index attempt")

        if type(lease_seconds) is not int or not 10 <= lease_seconds <= 600:
            raise ValueError("Lease seconds must be between 10 and 600")

        now = datetime.now(UTC)

        async with self.session_factory.begin() as session:
            matched = await session.scalar(
                update(KnowledgeVectorIndex)
                .where(
                    KnowledgeVectorIndex.profile_id == str(UUID(profile_id)),
                    KnowledgeVectorIndex.chunk_set_id == str(UUID(chunk_set_id)),
                    KnowledgeVectorIndex.status == "indexing",
                    # attempt 是 claim() 返回的执行序号。
                    # 新一轮领取会递增它，旧执行者因此无法续期。
                    KnowledgeVectorIndex.attempts == attempt,
                    # 已经过期的执行者必须重新领取，不能自行恢复租约。
                    KnowledgeVectorIndex.lease_until > now,
                )
                .values(
                    lease_until=now + timedelta(seconds=lease_seconds),
                    updated_at=now,
                )
                .returning(KnowledgeVectorIndex.attempts)
                .execution_options(synchronize_session=False)
            )

            if matched is None:
                raise VectorIndexLeaseLostError(
                    "Index lease is no longer valid"
                )

    async def finish(
        self,
        *,
        profile_id: str,
        chunk_set_id: str,
        attempt: int,
        succeeded: bool,
        point_count: int = 0,
    ) -> None:
        """确认本轮成功或失败，同时释放租约。"""

        if type(attempt) is not int or attempt < 1:
            raise ValueError("Invalid index attempt")

        if type(succeeded) is not bool:
            raise ValueError("Succeeded must be a boolean")

        if type(point_count) is not int or point_count < 0:
            raise ValueError("Invalid indexed point count")

        # 成功必须有实际完成数量；失败暂不声明完整可用的点数。
        if (
            succeeded and point_count == 0
        ) or (
            not succeeded and point_count != 0
        ):
            raise ValueError(
                "Point count does not match completion status"
            )

        now = datetime.now(UTC)

        statement = update(KnowledgeVectorIndex).where(
            KnowledgeVectorIndex.profile_id == str(UUID(profile_id)),
            KnowledgeVectorIndex.chunk_set_id == str(UUID(chunk_set_id)),
            KnowledgeVectorIndex.status == "indexing",
            KnowledgeVectorIndex.attempts == attempt,
            KnowledgeVectorIndex.lease_until > now,
        )

        if succeeded:
            # 数量比较与状态修改放在同一条 UPDATE 中。
            # 防止只完成部分写入，就把整个任务标记为 indexed。
            statement = statement.where(
                KnowledgeVectorIndex.expected_points == point_count
            )

        async with self.session_factory.begin() as session:
            matched = await session.scalar(
                statement.values(
                    status="indexed" if succeeded else "failed",
                    indexed_points=point_count,
                    indexed_at=now if succeeded else None,
                    lease_until=None,
                    # 这里只记录固定摘要，不直接保存 SDK 的异常文本。
                    # 原始异常可能包含请求内容或连接信息。
                    last_error=(
                        None
                        if succeeded
                        else "Index synchronization failed; retry required"
                    ),
                    updated_at=now,
                )
                .returning(KnowledgeVectorIndex.attempts)
                .execution_options(synchronize_session=False)
            )

            if matched is None:
                raise VectorIndexLeaseLostError(
                    "Index completion rejected: stale lease or point count mismatch"
                )