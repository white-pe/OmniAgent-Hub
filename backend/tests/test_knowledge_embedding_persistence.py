import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import event, func, select, update

from pawteam_api.config import Settings
from pawteam_api.database import (
    create_database_engine,
    create_session_factory,
)
from pawteam_api.knowledge.chunk_service import KnowledgeChunkingService
from pawteam_api.knowledge.embedding_client import EmbeddingRequestError
from pawteam_api.knowledge.embedding_persistence import (
    EmbeddingPersistenceConflictError,
    EmbeddingSourceNotFoundError,
    KnowledgeEmbeddingPersistenceService,
)
from pawteam_api.knowledge_schemas import KnowledgeChunkingConfig
from pawteam_api.models import (
    Base,
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeChunkEmbedding,
    KnowledgeDocument,
    KnowledgeDocumentParseResult,
    KnowledgeDocumentVersion,
    KnowledgeEmbeddingProfile,
    Provider,
    ProviderModel,
)
from pawteam_api.security.secret_store import SecretStore


@pytest.fixture
async def embedding_environment(tmp_path: Path):
    """创建真实数据库、加密密钥存储和三个可识别的文本片段。"""

    settings = Settings(
        environment="test",
        data_dir=tmp_path,
        secrets_dir=tmp_path / "secrets",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'persistence.db'}",
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        factory = create_session_factory(engine)
        secrets = SecretStore(settings)
        secrets.set("embedding-test-key", "fake-key")

        async with factory.begin() as session:
            provider = Provider(
                name="Persistence Provider",
                base_url="https://embedding.example/v1",
                api_key_ref="embedding-test-key",
            )
            knowledge = KnowledgeBase(name="Persistence Docs")
            session.add_all([provider, knowledge])
            await session.flush()

            session.add(
                ProviderModel(
                    provider_id=provider.id,
                    model_name="test-embedding",
                    display_name="Test Embedding",
                )
            )

            document = KnowledgeDocument(
                knowledge_base_id=knowledge.id,
                title="Guide",
            )
            session.add(document)
            await session.flush()

            version = KnowledgeDocumentVersion(
                document_id=document.id,
                version_number=1,
                original_filename="guide.txt",
                size_bytes=6,
                sha256="0" * 64,
                storage_key="test-only",
                status="parsed",
            )
            session.add(version)
            await session.flush()

            session.add(
                KnowledgeDocumentParseResult(
                    version_id=version.id,
                    text="123456",
                    char_count=6,
                    source_format="txt",
                    parser_name="utf8-text",
                    parser_version="1",
                )
            )
            profile = KnowledgeEmbeddingProfile(
                provider_id=provider.id,
                base_url=provider.base_url,
                model_name="test-embedding",
                model_revision="1",
                dimensions=2,
                send_dimensions=False,
                input_policy_version="raw-v1",
            )
            session.add(profile)
            await session.flush()

            ids = {
                "document_id": document.id,
                "version_id": version.id,
                "profile_id": profile.id,
            }
            provider_id = provider.id

        # 使用真实切块 Service，生成 "12"、"34"、"56"。
        chunk_set = await KnowledgeChunkingService(factory).create_chunk_set(
            ids["document_id"],
            ids["version_id"],
            KnowledgeChunkingConfig(chunk_size=2, chunk_overlap=0),
        )
        ids["chunk_set_id"] = chunk_set.id

        yield factory, secrets, ids, provider_id
    finally:
        await engine.dispose()


async def execute(environment, handler, **overrides):
    """只模拟网络边界，使用真实客户端和全部业务 Service。"""

    factory, secrets, ids, _ = environment
    parameters = {**ids, **overrides}

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as http_client:
        service = KnowledgeEmbeddingPersistenceService(
            session_factory=factory,
            secret_store=secrets,
            http_client=http_client,
            # 每批一条，便于观察中途失败。
            batch_size=1,
        )
        return await service.embed_chunk_set(**parameters)


def successful_response(request: httpx.Request) -> httpx.Response:
    """使用文本数字生成可识别的假向量。"""

    texts = json.loads(request.content)["input"]
    return httpx.Response(
        200,
        json={
            "data": [
                {"index": index, "embedding": [float(text), 1.0]}
                for index, text in enumerate(texts)
            ]
        },
    )


def unexpected_request(request: httpx.Request) -> httpx.Response:
    pytest.fail("This operation must not call the embedding provider")


async def vector_count(environment) -> int:
    factory, _, _, _ = environment
    async with factory() as session:
        return int(
            await session.scalar(
                select(func.count()).select_from(KnowledgeChunkEmbedding)
            )
            or 0
        )


async def test_persists_vectors_and_reuses_complete_result(
    embedding_environment,
) -> None:
    """首次保存完整结果，第二次执行不再访问模型。"""

    environment = embedding_environment
    first = await execute(environment, successful_response)

    assert first.chunk_count == 3
    assert first.reused is False
    assert await vector_count(environment) == 3

    factory, _, ids, _ = environment
    async with factory() as session:
        records = (
            await session.execute(
                select(KnowledgeChunk.text, KnowledgeChunkEmbedding.vector)
                .join(
                    KnowledgeChunkEmbedding,
                    KnowledgeChunkEmbedding.chunk_id == KnowledgeChunk.id,
                )
                .where(KnowledgeChunkEmbedding.profile_id == ids["profile_id"])
                .order_by(KnowledgeChunk.chunk_index)
            )
        ).all()

    assert [(text, vector) for text, vector in records] == [
        ("12", [12.0, 1.0]),
        ("34", [34.0, 1.0]),
        ("56", [56.0, 1.0]),
    ]

    repeated = await execute(environment, unexpected_request)
    assert repeated.reused is True
    assert await vector_count(environment) == 3


async def test_upstream_failure_saves_nothing(embedding_environment) -> None:
    """第二次模型请求失败，第一批结果也不能部分落库。"""

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 2:
            return httpx.Response(429)
        return successful_response(request)

    with pytest.raises(EmbeddingRequestError):
        await execute(embedding_environment, handler)

    assert calls == 2
    assert await vector_count(embedding_environment) == 0


async def test_database_failure_rolls_back_vectors(
    embedding_environment,
) -> None:
    """插入过程中发生异常，事务必须回滚全部向量。"""

    inserted = 0

    def fail_after_insert(mapper, connection, target) -> None:
        nonlocal inserted
        inserted += 1
        if inserted == 2:
            raise RuntimeError("simulated write failure")

    event.listen(KnowledgeChunkEmbedding, "after_insert", fail_after_insert)
    try:
        with pytest.raises(RuntimeError, match="simulated write failure"):
            await execute(embedding_environment, successful_response)
    finally:
        # 必须移除事件监听，避免影响其他测试。
        event.remove(KnowledgeChunkEmbedding, "after_insert", fail_after_insert)

    assert await vector_count(embedding_environment) == 0


async def test_partial_existing_result_is_rejected(
    embedding_environment,
) -> None:
    """只有部分记录时，不认为成功，也不偷偷覆盖或补齐。"""

    factory, _, ids, _ = embedding_environment
    async with factory.begin() as session:
        chunk_id = await session.scalar(
            select(KnowledgeChunk.id)
            .where(KnowledgeChunk.chunk_set_id == ids["chunk_set_id"])
            .order_by(KnowledgeChunk.chunk_index)
        )
        session.add(
            KnowledgeChunkEmbedding(
                profile_id=ids["profile_id"],
                chunk_id=chunk_id,
                vector=[12.0, 1.0],
            )
        )

    with pytest.raises(EmbeddingPersistenceConflictError, match="incomplete"):
        await execute(embedding_environment, unexpected_request)

    assert await vector_count(embedding_environment) == 1


@pytest.mark.parametrize("change", ["address", "policy"])
async def test_invalid_configuration_fails_before_request(
    embedding_environment,
    change: str,
) -> None:
    """地址漂移和未支持的输入策略，都必须在模型调用前失败。"""

    factory, _, ids, provider_id = embedding_environment

    async with factory.begin() as session:
        if change == "address":
            await session.execute(
                update(Provider)
                .where(Provider.id == provider_id)
                .values(base_url="https://changed.example/v1")
            )
        else:
            await session.execute(
                update(KnowledgeEmbeddingProfile)
                .where(KnowledgeEmbeddingProfile.id == ids["profile_id"])
                .values(input_policy_version="unsupported-v2")
            )

    with pytest.raises(EmbeddingPersistenceConflictError):
        await execute(embedding_environment, unexpected_request)

    assert await vector_count(embedding_environment) == 0


async def test_source_change_during_generation_is_detected(
    embedding_environment,
) -> None:
    """模拟调用模型期间文本被改动，旧文本向量不能继续保存。"""

    factory, _, ids, _ = embedding_environment
    changed = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal changed
        if not changed:
            changed = True
            async with factory.begin() as session:
                await session.execute(
                    update(KnowledgeChunk)
                    .where(
                        KnowledgeChunk.chunk_set_id == ids["chunk_set_id"],
                        KnowledgeChunk.chunk_index == 0,
                    )
                    .values(text="99")
                )
        return successful_response(request)

    with pytest.raises(
        EmbeddingPersistenceConflictError,
        match="changed during generation",
    ):
        await execute(embedding_environment, handler)

    assert await vector_count(embedding_environment) == 0


async def test_wrong_document_cannot_use_chunk_set(
    embedding_environment,
) -> None:
    """即使批次 ID 正确，也不能通过错误文档路径访问。"""

    with pytest.raises(EmbeddingSourceNotFoundError):
        await execute(
            embedding_environment,
            unexpected_request,
            document_id="wrong-document",
        )


async def test_invalid_saved_vector_is_not_reused(
    embedding_environment,
) -> None:
    """记录齐全但包含坏向量，也不能直接报告成功。"""

    await execute(embedding_environment, successful_response)

    factory, _, ids, _ = embedding_environment
    async with factory.begin() as session:
        await session.execute(
            update(KnowledgeChunkEmbedding)
            .where(KnowledgeChunkEmbedding.profile_id == ids["profile_id"])
            .values(vector=[0.0, 0.0])
        )

    with pytest.raises(
        EmbeddingPersistenceConflictError,
        match="failed validation",
    ):
        await execute(embedding_environment, unexpected_request)