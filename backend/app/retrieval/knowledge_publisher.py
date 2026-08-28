from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from redis.asyncio import Redis

from app.config import Settings
from app.retrieval.chunk_splitter import KnowledgeTextSplitter, TextChunk
from app.retrieval.embedding import DoubaoEmbeddingClient, vector_to_bytes

class KnowledgeQuestionInput(BaseModel):
    """Java数据库中的标准问法身份和展示文本。"""

    question_id: int = Field(gt=0)
    question_no: int = Field(ge=0)
    text: str = Field(min_length=1)


class KnowledgeChunkInput(BaseModel):
    """Java提交的原子分片及标准问法。

    新页面提交时由Java校验至少一个标准问法；这里允许空列表，是为了重建迁移期已经
    发布、只有分片而没有问法的历史知识。历史知识仍会生成正文向量，但不会生成别名向量。
    """

    chunk_no: int = Field(ge=0)
    content: str = Field(min_length=1)
    questions: list[KnowledgeQuestionInput] = Field(default_factory=list, max_length=8)

class KnowledgePublishRequest(BaseModel):
    """Java审批通过后发送的不可变知识版本。"""

    knowledge_id: int = Field(gt=0)
    knowledge_code: str = Field(min_length=1, max_length=64)
    version_id: int = Field(gt=0)
    version_no: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1)
    category: str = Field(min_length=1, max_length=128)
    tags: list[str] = Field(default_factory=list, max_length=20)
    intent: str = Field(min_length=1, max_length=64)
    effective_at: datetime
    expired_at: datetime | None = None
    chunks: list[KnowledgeChunkInput] = Field(default_factory=list, max_length=100)
    # testing文档进入同一索引但不会被线上只过滤approved的查询召回。
    index_status: Literal["approved", "testing"] = "approved"

    @model_validator(mode="after")
    def validate_business_time(self) -> "KnowledgePublishRequest":
        """拒绝时间范围倒置的数据，避免无效知识进入检索索引。"""
        if self.expired_at is not None and self.expired_at <= self.effective_at:
            raise ValueError("expired_at必须晚于effective_at")
        if self.chunks:
            chunk_numbers = [chunk.chunk_no for chunk in self.chunks]
            if chunk_numbers != list(range(len(self.chunks))):
                raise ValueError("chunk_no必须从0开始连续递增")
            all_question_ids = [
                question.question_id
                for chunk in self.chunks
                for question in chunk.questions
            ]
            if len(all_question_ids) != len(set(all_question_ids)):
                raise ValueError("标准问法ID在整个知识版本中不能重复")
            for chunk in self.chunks:
                normalized = [question.text.strip() for question in chunk.questions]
                if any(not question for question in normalized):
                    raise ValueError("标准问法不能为空")
                if len(normalized) != len(set(normalized)):
                    raise ValueError("同一分片的标准问法不能重复")
                question_numbers = [question.question_no for question in chunk.questions]
                if question_numbers != list(range(len(chunk.questions))):
                    raise ValueError("question_no必须从0开始连续递增")
        return self


class KnowledgeDeleteRequest(BaseModel):
    """停用知识时只需稳定身份和历史YAML编码。"""

    knowledge_id: int = Field(gt=0)
    knowledge_code: str = Field(min_length=1, max_length=64)


class PublishedQuestion(BaseModel):
    """标准问法独立向量文档的同步结果。"""

    question_id: int
    question_no: int
    text: str
    question_hash: str
    redis_key: str

class PublishedChunk(BaseModel):
    """返回给Java落库的切片元数据，不返回向量。"""

    chunk_no: int
    content: str
    content_hash: str
    redis_key: str
    index_version: int = 1
    questions: list[PublishedQuestion] = Field(default_factory=list)


class KnowledgePublishResponse(BaseModel):
    knowledge_id: int
    version_id: int
    chunks: list[PublishedChunk]


class RedisKnowledgePublisher:
    """将一个审批版本原子式替换为一组Redis Search Hash文档。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._redis: Redis | None = None
        self._embedding = DoubaoEmbeddingClient(settings)
        self._splitter = KnowledgeTextSplitter()

    async def initialize(self) -> None:
        self._redis = Redis.from_url(self.settings.redis_url, decode_responses=False)
        await self._redis.ping()

    async def close(self) -> None:
        await self._embedding.close()
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def publish(self, payload: KnowledgePublishRequest) -> KnowledgePublishResponse:
        now = datetime.now(timezone.utc)
        effective_at = payload.effective_at.astimezone(timezone.utc)
        expired_at = payload.expired_at.astimezone(timezone.utc) if payload.expired_at else None
        if effective_at > now or (expired_at is not None and expired_at <= now):
            # 尚未生效或已经过期时保持数据库版本，但不放入当前检索索引。
            await self.delete(KnowledgeDeleteRequest(
                knowledge_id=payload.knowledge_id,
                knowledge_code=payload.knowledge_code,
            ))
            return KnowledgePublishResponse(
                knowledge_id=payload.knowledge_id,
                version_id=payload.version_id,
                chunks=[],
            )

        if payload.chunks:
            questions_by_chunk = {
                item.chunk_no: tuple(item.questions) for item in payload.chunks
            }
            chunks = [
                TextChunk(
                    chunk_no=item.chunk_no,
                    content=item.content.strip(),
                    content_hash=hashlib.sha256(
                        item.content.strip().encode("utf-8")
                    ).hexdigest(),
                    questions=tuple(question.text.strip() for question in item.questions),
                )
                for item in payload.chunks
            ]
        else:
            # 兼容没有保存分片的历史版本，仍使用原有切片器发布。
            chunks = self._splitter.split(payload.content)
            questions_by_chunk = {}
        semaphore = asyncio.Semaphore(3)

        async def embed_text(value: str) -> bytes:
            async with semaphore:
                vector = await self._embedding.embed(value)
            return vector_to_bytes(vector)

        async def embed(chunk: TextChunk) -> tuple[TextChunk, bytes, list[bytes]]:
            semantic_text = "\n".join(filter(None, [
                f"分类：{payload.category}",
                f"标题：{payload.title}",
                f"标签：{'、'.join(payload.tags)}" if payload.tags else "",
                chunk.content,
            ]))
            vectors = await asyncio.gather(
                embed_text(semantic_text),
                *(embed_text(question) for question in chunk.questions),
            )
            return chunk, vectors[0], list(vectors[1:])

        embedded = await asyncio.gather(*(embed(chunk) for chunk in chunks))
        client = self._require_redis()
        key_set = self._key_set(payload.knowledge_id)
        old_keys = set(await client.smembers(key_set))
        new_keys: list[bytes] = []
        response_chunks: list[PublishedChunk] = []

        pipeline = client.pipeline(transaction=True)
        for chunk, vector_blob, question_vectors in embedded:
            redis_key = (
                f"{self.settings.knowledge_key_prefix}{payload.knowledge_id}:"
                f"{payload.version_id}:{chunk.chunk_no}"
            )
            redis_key_bytes = redis_key.encode("utf-8")
            new_keys.append(redis_key_bytes)
            pipeline.hset(redis_key, mapping={
                "id": f"{payload.knowledge_id}:{payload.version_id}:{chunk.chunk_no}",
                "question": payload.title,
                "answer": chunk.content,
                "category": payload.category,
                "intent": payload.intent,
                "status": payload.index_status,
                "created_at": int(time.time()),
                "knowledge_id": payload.knowledge_id,
                "version_id": payload.version_id,
                "chunk_no": chunk.chunk_no,
                "content_hash": chunk.content_hash,
                "index_version": 1,
                "embedding": vector_blob,
            })

            published_questions: list[PublishedQuestion] = []
            question_inputs = questions_by_chunk.get(chunk.chunk_no, ())
            for question_input, question_vector in zip(
                    question_inputs, question_vectors, strict=True):
                question_no = question_input.question_no
                question = question_input.text.strip()
                question_hash = hashlib.sha256(question.encode("utf-8")).hexdigest()
                question_key = f"{redis_key}:q:{question_no}"
                mapping_key = (
                    f"{self.settings.knowledge_question_map_key_prefix}"
                    f"{question_input.question_id}"
                )
                new_keys.append(question_key.encode("utf-8"))
                new_keys.append(mapping_key.encode("utf-8"))
                pipeline.hset(question_key, mapping={
                    # 多个别名共享稳定source_id，命中后统一返回所属原子分片。
                    "id": f"{payload.knowledge_id}:{payload.version_id}:{chunk.chunk_no}",
                    "question": question,
                    "answer": chunk.content,
                    "category": payload.category,
                    "intent": payload.intent,
                    "status": payload.index_status,
                    "created_at": int(time.time()),
                    "knowledge_id": payload.knowledge_id,
                    "version_id": payload.version_id,
                    "chunk_no": chunk.chunk_no,
                    "content_hash": chunk.content_hash,
                    "question_hash": question_hash,
                    "question_id": question_input.question_id,
                    "index_version": 1,
                    "embedding": question_vector,
                })
                pipeline.set(mapping_key, question_key)
                published_questions.append(PublishedQuestion(
                    question_id=question_input.question_id,
                    question_no=question_no,
                    text=question,
                    question_hash=question_hash,
                    redis_key=question_key,
                ))

            response_chunks.append(PublishedChunk(
                chunk_no=chunk.chunk_no,
                content=chunk.content,
                content_hash=chunk.content_hash,
                redis_key=redis_key,
                questions=published_questions,
            ))

        pipeline.delete(key_set)
        if new_keys:
            pipeline.sadd(key_set, *new_keys)
        stale_keys = old_keys.difference(new_keys)
        if stale_keys:
            pipeline.delete(*stale_keys)
        # 清除旧YAML发布方式使用的单键，完成平滑迁移。
        pipeline.delete(f"{self.settings.knowledge_key_prefix}{payload.knowledge_code}")
        await pipeline.execute()
        return KnowledgePublishResponse(
            knowledge_id=payload.knowledge_id,
            version_id=payload.version_id,
            chunks=response_chunks,
        )

    async def delete(self, payload: KnowledgeDeleteRequest) -> None:
        client = self._require_redis()
        key_set = self._key_set(payload.knowledge_id)
        keys = list(await client.smembers(key_set))
        pipeline = client.pipeline(transaction=True)
        if keys:
            pipeline.delete(*keys)
        pipeline.delete(key_set)
        pipeline.delete(f"{self.settings.knowledge_key_prefix}{payload.knowledge_code}")
        await pipeline.execute()

    def _key_set(self, knowledge_id: int) -> str:
        return f"cs:knowledge:keys:{knowledge_id}"

    def _require_redis(self) -> Redis:
        if self._redis is None:
            raise RuntimeError("RedisKnowledgePublisher尚未初始化")
        return self._redis


def create_knowledge_router(settings: Settings) -> APIRouter:
    """创建Java专用内部接口，令牌复用现有Tool内部令牌。"""
    router = APIRouter(prefix="/api/internal/knowledge", tags=["internal-knowledge"])

    def verify_token(value: str) -> None:
        expected = settings.business_tool_internal_token.strip()
        if not expected or not hmac.compare_digest(value, expected):
            raise HTTPException(status_code=401, detail="内部调用身份校验失败")

    @router.post("/publish", response_model=KnowledgePublishResponse)
    async def publish(
        request: Request,
        x_internal_token: str = Header(default="", alias="X-Internal-Token"),
    ) -> KnowledgePublishResponse:
        verify_token(x_internal_token)
        raw_body = await request.body()
        if not raw_body:
            content_length = request.headers.get("content-length", "missing")
            raise HTTPException(
                status_code=400,
                detail=f"知识发布请求体为空，content-length={content_length}",
            )
        try:
            payload = KnowledgePublishRequest.model_validate_json(raw_body)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        publisher: RedisKnowledgePublisher = request.app.state.knowledge_publisher
        return await publisher.publish(payload)

    @router.post("/delete", status_code=204)
    async def delete(
        payload: KnowledgeDeleteRequest,
        request: Request,
        x_internal_token: str = Header(default="", alias="X-Internal-Token"),
    ) -> None:
        verify_token(x_internal_token)
        publisher: RedisKnowledgePublisher = request.app.state.knowledge_publisher
        await publisher.delete(payload)

    return router
