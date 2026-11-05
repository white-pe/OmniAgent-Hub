"""Qdrant adapter for validated vectors and scoped retrieval."""

from dataclasses import dataclass
from math import isfinite
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError
from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from pawteam_api.knowledge.embeddings import EmbeddingBatch


class VectorCollectionConflictError(RuntimeError):
    """已有集合的向量配置与当前 Profile 不一致。"""


class VectorMetadata(BaseModel):
    """只保存关联信息，正文仍从关系数据库读取。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # UUID 类型会校验输入，并在序列化时输出统一格式。
    profile_id: UUID
    knowledge_base_id: UUID
    document_id: UUID
    version_id: UUID
    chunk_set_id: UUID
    chunk_id: UUID


@dataclass(frozen=True)
class VectorIndexPoint:
    """一次索引写入需要的关联信息与向量。"""

    metadata: VectorMetadata
    vector: tuple[float, ...]


@dataclass(frozen=True)
class VectorSearchHit:
    """检索命中只返回关联信息和分数，不返回向量正文。"""

    metadata: VectorMetadata
    score: float


class QdrantVectorStore:
    """封装 Qdrant SDK，不负责生成向量或判断用户权限。"""

    max_upsert_points = 128

    def __init__(
        self,
        *,
        client: AsyncQdrantClient,
        profile_id: str,
        dimensions: int,
    ) -> None:
        if type(dimensions) is not int or dimensions < 1:
            raise ValueError("Vector dimensions must be a positive integer")

        self.client = client
        self.profile_id = UUID(profile_id)
        self.dimensions = dimensions

        # 使用规范化 UUID 生成固定名称。
        # 集合不会因为重启、重试而变成另一个名称。
        self.collection_name = (
            f"omniagent_embedding_{self.profile_id.hex}"
        )

    async def initialize(self) -> None:
        """不存在则创建；已存在时检查配置，绝不自动删除重建。"""

        exists = await self.client.collection_exists(self.collection_name)

        if not exists:
            try:
                await self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=self.dimensions,
                        distance=models.Distance.COSINE,
                    ),
                )
            except UnexpectedResponse as error:
                # 两个远程初始化请求可能同时发现集合不存在。
                # 仅允许“已经存在”的冲突继续进入配置检查；
                # 网络、鉴权等其他错误必须保留。
                if error.status_code != 409:
                    raise

        await self._check_collection()

    async def _check_collection(self) -> None:
        """写入和搜索前确认维度与距离函数一致。"""

        info = await self.client.get_collection(self.collection_name)
        config = info.config.params.vectors

        # 本轮使用单个未命名稠密向量，不接受其他集合结构。
        if (
            not isinstance(config, models.VectorParams)
            or config.size != self.dimensions
            or config.distance != models.Distance.COSINE
        ):
            raise VectorCollectionConflictError(
                "Collection configuration does not match embedding profile"
            )

    async def upsert(
        self,
        points: list[VectorIndexPoint],
    ) -> None:
        """校验完整输入后写入一批点；批次大小由上层控制。"""

        if (
            not isinstance(points, list)
            or not 1 <= len(points) <= self.max_upsert_points
        ):
            raise ValueError("Invalid vector upsert batch size")

        chunk_ids: set[UUID] = set()

        for point in points:
            if not isinstance(point, VectorIndexPoint):
                raise ValueError("Invalid vector index point")

            if not isinstance(point.metadata, VectorMetadata):
                raise ValueError("Invalid vector metadata")

            if point.metadata.profile_id != self.profile_id:
                raise ValueError("Point belongs to another embedding profile")

            if point.metadata.chunk_id in chunk_ids:
                raise ValueError("Duplicate chunk ID in vector batch")
            chunk_ids.add(point.metadata.chunk_id)

        # 复用统一向量校验，避免把错误维度或零向量写入索引。
        validated = EmbeddingBatch(
            dimensions=self.dimensions,
            vectors=[list(point.vector) for point in points],
        )

        records = [
            models.PointStruct(
                id=str(point.metadata.chunk_id),
                vector=vector,
                payload=point.metadata.model_dump(mode="json"),
            )
            for point, vector in zip(
                points,
                validated.vectors,
                strict=True,
            )
        ]

        await self._check_collection()

        result = await self.client.upsert(
            collection_name=self.collection_name,
            points=records,
            wait=True,
        )
        if result.status != models.UpdateStatus.COMPLETED:
            raise RuntimeError("Vector upsert did not complete")

    async def search(
        self,
        *,
        vector: list[float],
        allowed_knowledge_base_ids: list[str],
        limit: int = 10,
        allowed_chunk_set_ids: list[str] | None = None,
    ) -> list[VectorSearchHit]:
        """在明确允许的知识库范围内搜索，空范围不执行查询。"""

        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Search limit must be between 1 and 100")

        if not isinstance(allowed_knowledge_base_ids, list):
            raise ValueError("Knowledge base scope must be a list")

        allowed = {
            str(UUID(value))
            for value in allowed_knowledge_base_ids
        }

        # 关键边界：没有授权范围时返回空结果。
        # 不能省略过滤条件后变成整个集合搜索。
        if not allowed:
            return []
        # 发布过滤在召回前执行，避免旧版本占满 top-k 后才被应用丢弃。
        chunk_filter = []
        if allowed_chunk_set_ids is not None:
            if not allowed_chunk_set_ids:
                return []
            chunk_filter = [
                models.FieldCondition(
                    key="chunk_set_id",
                    match=models.MatchAny(
                        any=sorted({str(UUID(value)) for value in allowed_chunk_set_ids})
                    ),
                )
            ]

        validated = EmbeddingBatch(
            dimensions=self.dimensions,
            vectors=[vector],
        )

        await self._check_collection()

        response = await self.client.query_points(
            collection_name=self.collection_name,
            query=validated.vectors[0],
            query_filter=models.Filter(
                must=[
                    *chunk_filter,
                    models.FieldCondition(
                        key="profile_id",
                        match=models.MatchValue(
                            value=str(self.profile_id),
                        ),
                    ),
                    models.FieldCondition(
                        key="knowledge_base_id",
                        match=models.MatchAny(any=sorted(allowed)),
                    ),
                ]
            ),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )

        hits: list[VectorSearchHit] = []

        for point in response.points:
            try:
                metadata = VectorMetadata.model_validate(point.payload)
            except ValidationError as error:
                raise RuntimeError(
                    "Search returned invalid vector metadata"
                ) from error

            # 对返回数据做一致性复查，不能盲目信任索引中的关联信息。
            if (
                metadata.profile_id != self.profile_id
                or str(metadata.knowledge_base_id) not in allowed
                or str(point.id) != str(metadata.chunk_id)
                or not isfinite(point.score)
                or (
                    allowed_chunk_set_ids is not None
                    and str(metadata.chunk_set_id) not in allowed_chunk_set_ids
                )
            ):
                raise RuntimeError("Search result failed consistency checks")

            hits.append(
                VectorSearchHit(
                    metadata=metadata,
                    score=float(point.score),
                )
            )

        return hits

    async def count_chunk_set(self, chunk_set_id: str) -> int:
        """核对远端真实点数，避免只相信数据库中的历史完成状态。"""

        await self._check_collection()
        result = await self.client.count(
            collection_name=self.collection_name,
            count_filter=models.Filter(must=[
                models.FieldCondition(
                    key="profile_id", match=models.MatchValue(value=str(self.profile_id))
                ),
                models.FieldCondition(
                    key="chunk_set_id", match=models.MatchValue(value=str(UUID(chunk_set_id)))
                ),
            ]),
            exact=True,
        )
        return result.count

    async def delete_document(
        self,
        *,
        knowledge_base_id: str,
        document_id: str,
    ) -> None:
        """删除当前 Profile、指定知识库和文档下的所有点。"""

        knowledge_id = str(UUID(knowledge_base_id))
        document_id = str(UUID(document_id))

        await self._check_collection()

        result = await self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="profile_id",
                            match=models.MatchValue(
                                value=str(self.profile_id),
                            ),
                        ),
                        models.FieldCondition(
                            key="knowledge_base_id",
                            match=models.MatchValue(value=knowledge_id),
                        ),
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id),
                        ),
                    ]
                )
            ),
            wait=True,
        )
        if result.status != models.UpdateStatus.COMPLETED:
            raise RuntimeError("Vector deletion did not complete")
