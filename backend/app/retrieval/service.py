from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any, Protocol

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.config import Settings
from app.retrieval.embedding import DoubaoEmbeddingClient, vector_to_bytes
from app.retrieval.schemas import SemanticAnswerHit, SemanticLookup


logger = logging.getLogger("smart_customer_service.semantic_cache")
_SAFE_INTENT = re.compile(r"^[a-z0-9_]+$")
_GENERIC_KNOWLEDGE_INTENT = "knowledge_query"


class SemanticAnswerService(Protocol):
    """编排器依赖的语义检索接口，真实Redis实现和关闭实现都遵守它。"""

    async def initialize(self) -> None:
        """初始化外部连接和索引。"""

    async def lookup(self, question: str, intent: str) -> SemanticLookup:
        """依次查询审核知识库和LangCache。"""

    async def record_generated_answer(
        self,
        question: str,
        answer: str,
        intent: str,
        actor_id: str,
        lookup: SemanticLookup,
    ) -> bool:
        """记录缺口频次，达到门槛时写入LangCache。"""

    async def health_check(self) -> bool:
        """检查语义检索依赖是否可用。"""

    async def close(self) -> None:
        """释放连接。"""


class DisabledSemanticAnswerService:
    """语义检索关闭时使用的空实现，避免编排器到处判断None。"""

    async def initialize(self) -> None:
        """关闭状态不需要初始化。"""

    async def lookup(self, question: str, intent: str) -> SemanticLookup:
        """关闭状态始终返回未命中。"""
        return SemanticLookup()

    async def record_generated_answer(
        self,
        question: str,
        answer: str,
        intent: str,
        actor_id: str,
        lookup: SemanticLookup,
    ) -> bool:
        """关闭状态不记录模型回答。"""
        return False

    async def health_check(self) -> bool:
        """关闭是主动配置，不视为故障。"""
        return True

    async def close(self) -> None:
        """空实现没有连接需要释放。"""


class RedisSemanticAnswerService:
    """用Redis Search实现审核知识库与自建LangCache。

    三个索引职责不同：
    1. knowledge只保存人工确认的标准知识，命中后直接返回。
    2. langcache只保存高频缺口的模型答案，使用更严格阈值和短TTL。
    3. langcache-gap只统计相似问题簇及不同会话数，不直接对用户返回答案。
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._redis: Redis | None = None
        self._embedding = DoubaoEmbeddingClient(settings)

    async def initialize(self) -> None:
        """连接Redis并创建三个向量索引。

        索引已存在时保留原数据；配置维度变化时应由发布流程显式重建索引。
        """
        if not self.settings.has_real_embedding_api_key:
            raise RuntimeError("已启用语义检索，但没有配置真实EMBEDDING_API_KEY")

        self._redis = Redis.from_url(
            self.settings.redis_url,
            decode_responses=False,
            # 语义检索连接可能长时间空闲，使用健康检查和超时重试淘汰失效连接。
            health_check_interval=30,
            socket_connect_timeout=5,
            socket_timeout=8,
            retry_on_timeout=True,
        )
        await self._redis.ping()
        await self._ensure_indexes()

    async def lookup(self, question: str, intent: str) -> SemanticLookup:
        """先查审核知识，再查短期LangCache，并复用同一个问题向量。"""
        if intent not in self.settings.semantic_cache_intent_set:
            return SemanticLookup()
        if not _SAFE_INTENT.fullmatch(intent):
            logger.warning("拒绝包含非法字符的语义检索意图: %s", intent)
            return SemanticLookup()

        try:
            vector_blob = vector_to_bytes(await self._embedding.embed(question))

            knowledge_hit = await self._search(
                index_name=self.settings.knowledge_index_name,
                vector_blob=vector_blob,
                intent=intent,
                statuses="approved",
                top_k=self.settings.knowledge_top_k,
                distance_threshold=self.settings.knowledge_distance_threshold,
                provider="redis-search:knowledge",
            )
            if knowledge_hit:
                return SemanticLookup(hit=knowledge_hit, vector_blob=vector_blob, attempted=True)

            cache_hit = await self._search(
                index_name=self.settings.langcache_index_name,
                vector_blob=vector_blob,
                intent=intent,
                statuses="approved|unreviewed",
                top_k=1,
                distance_threshold=self.settings.langcache_distance_threshold,
                provider="redis-search:langcache",
            )
            return SemanticLookup(hit=cache_hit, vector_blob=vector_blob, attempted=True)
        except Exception:
            # 语义缓存属于加速与知识增强层，短暂故障时降级到原回答模型，不中断聊天。
            logger.exception("Redis语义检索失败，已降级到回答模型")
            return SemanticLookup(failed=True)

    async def record_generated_answer(
        self,
        question: str,
        answer: str,
        intent: str,
        actor_id: str,
        lookup: SemanticLookup,
    ) -> bool:
        """按相似问题簇统计不同会话，达到门槛后缓存本次成功答案。

        这里写入unreviewed状态并设置短TTL。后续审核后台可以将可靠答案提升为
        approved知识；Tool结果、投诉、转人工和模型降级答案不会调用本方法。
        """
        if (
            intent not in self.settings.semantic_cache_intent_set
            or not lookup.vector_blob
            or not answer.strip()
            or not actor_id.strip()
        ):
            return False

        try:
            gap = await self._find_gap(lookup.vector_blob, intent)
            gap_id = gap["id"] if gap else str(uuid.uuid4())
            gap_key = f"{self.settings.langcache_gap_key_prefix}{gap_id}"
            actor_key = f"{gap_key}:actors"
            client = self._require_redis()

            if not gap:
                await client.hset(
                    gap_key,
                    mapping={
                        "id": gap_id,
                        "question": question,
                        "intent": intent,
                        "updated_at": int(time.time()),
                        "embedding": lookup.vector_blob,
                    },
                )
            else:
                await client.hset(gap_key, mapping={"updated_at": int(time.time())})

            # SET天然去重，同一个会话重复提问只计算一次，减少刷缓存风险。
            await client.sadd(actor_key, actor_id)
            await client.expire(gap_key, self.settings.langcache_gap_window_seconds)
            await client.expire(actor_key, self.settings.langcache_gap_window_seconds)
            distinct_actors = int(await client.scard(actor_key))
            if distinct_actors < self.settings.langcache_frequency_threshold:
                return False

            cache_id = str(uuid.uuid4())
            cache_key = f"{self.settings.langcache_key_prefix}{cache_id}"
            await client.hset(
                cache_key,
                mapping={
                    "id": cache_id,
                    "question": question,
                    "answer": answer,
                    "intent": intent,
                    "status": "unreviewed",
                    "source": "frequent_gap",
                    "created_at": int(time.time()),
                    "embedding": lookup.vector_blob,
                },
            )
            await client.expire(cache_key, self.settings.langcache_ttl_seconds)
            await client.delete(gap_key, actor_key)
            logger.info(
                "高频缺口已写入LangCache: intent=%s, distinct_actors=%s",
                intent,
                distinct_actors,
            )
            return True
        except Exception:
            # 缓存回写失败不能影响已经生成好的客服回答。
            logger.exception("LangCache缺口统计或回写失败")
            return False

    async def health_check(self) -> bool:
        """同时检查Redis连接和知识索引是否存在。"""
        try:
            client = self._require_redis()
            await client.ping()
            await client.execute_command("FT.INFO", self.settings.knowledge_index_name)
            return True
        except Exception:
            return False

    async def close(self) -> None:
        """关闭Embedding HTTP连接池和Redis连接池。"""
        await self._embedding.close()
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def _ensure_indexes(self) -> None:
        """按各自数据结构创建知识、缓存和缺口索引。"""
        await self._create_vector_index(
            self.settings.knowledge_index_name,
            self.settings.knowledge_key_prefix,
            (
                "id", "TAG",
                "question", "TEXT",
                "answer", "TEXT",
                "category", "TAG",
                "intent", "TAG",
                "status", "TAG",
                "created_at", "NUMERIC",
            ),
        )
        await self._create_vector_index(
            self.settings.langcache_index_name,
            self.settings.langcache_key_prefix,
            (
                "id", "TAG",
                "question", "TEXT",
                "answer", "TEXT",
                "intent", "TAG",
                "status", "TAG",
                "source", "TAG",
                "created_at", "NUMERIC",
            ),
        )
        await self._create_vector_index(
            self.settings.langcache_gap_index_name,
            self.settings.langcache_gap_key_prefix,
            (
                "id", "TAG",
                "question", "TEXT",
                "intent", "TAG",
                "updated_at", "NUMERIC",
            ),
        )

    async def _create_vector_index(
        self,
        index_name: str,
        key_prefix: str,
        fields: tuple[str, ...],
    ) -> None:
        """创建HASH向量索引；已存在属于正常启动场景。"""
        command: list[Any] = [
            "FT.CREATE",
            index_name,
            "ON",
            "HASH",
            "PREFIX",
            "1",
            key_prefix,
            "SCHEMA",
            *fields,
            "embedding",
            "VECTOR",
            "HNSW",
            "6",
            "TYPE",
            "FLOAT32",
            "DIM",
            str(self.settings.embedding_dimension),
            "DISTANCE_METRIC",
            "COSINE",
        ]
        try:
            await self._require_redis().execute_command(*command)
        except ResponseError as exc:
            if "Index already exists" not in str(exc):
                raise

    async def _search(
        self,
        index_name: str,
        vector_blob: bytes,
        intent: str,
        statuses: str,
        top_k: int,
        distance_threshold: float,
        provider: str,
    ) -> SemanticAnswerHit | None:
        """执行带审核状态过滤的KNN余弦距离查询。

        新版LLM把所有纯知识问题统一为knowledge_query，但Redis中已发布的
        历史知识仍保留activity_rules等细分意图。通用知识路由不能再按
        intent精确过滤，应该依靠向量相似度跨旧意图召回；旧路由仍保留过滤。
        """
        query = self._build_search_query(intent, statuses, top_k)
        raw = await self._require_redis().execute_command(
            "FT.SEARCH",
            index_name,
            query,
            "PARAMS",
            "2",
            "vector",
            vector_blob,
            "SORTBY",
            "vector_distance",
            "ASC",
            "RETURN",
            "3",
            "id",
            "answer",
            "vector_distance",
            "DIALECT",
            "2",
        )
        rows = self._parse_search_rows(raw)
        if not rows:
            return None
        distance = float(rows[0].get("vector_distance", "1"))
        if distance > distance_threshold:
            return None
        return SemanticAnswerHit(
            answer=rows[0].get("answer", ""),
            provider=provider,
            distance=distance,
            source_id=rows[0].get("id", ""),
        )

    async def _find_gap(self, vector_blob: bytes, intent: str) -> dict[str, str] | None:
        """查找同意图下足够相似的缺口簇。"""
        # knowledge_query是统一知识路由，需要兼容旧意图下已存在的缺口簇。
        intent_filter = (
            "*"
            if intent == _GENERIC_KNOWLEDGE_INTENT
            else f"@intent:{{{intent}}}"
        )
        query = f"({intent_filter})=>[KNN 1 @embedding $vector AS vector_distance]"
        raw = await self._require_redis().execute_command(
            "FT.SEARCH",
            self.settings.langcache_gap_index_name,
            query,
            "PARAMS",
            "2",
            "vector",
            vector_blob,
            "SORTBY",
            "vector_distance",
            "ASC",
            "RETURN",
            "2",
            "id",
            "vector_distance",
            "DIALECT",
            "2",
        )
        rows = self._parse_search_rows(raw)
        if not rows:
            return None
        distance = float(rows[0].get("vector_distance", "1"))
        if distance > self.settings.langcache_distance_threshold:
            return None
        return rows[0]

    @staticmethod
    def _build_search_query(intent: str, statuses: str, top_k: int) -> str:
        """构造知识库和LangCache共用的向量查询。"""
        status_filter = f"@status:{{{statuses}}}"
        metadata_filter = (
            status_filter
            if intent == _GENERIC_KNOWLEDGE_INTENT
            else f"@intent:{{{intent}}} {status_filter}"
        )
        return (
            f"({metadata_filter})"
            f"=>[KNN {top_k} @embedding $vector AS vector_distance]"
        )

    def _parse_search_rows(self, raw: Any) -> list[dict[str, str]]:
        """把redis-py返回的FT.SEARCH数组转换为普通字典列表。"""
        if not isinstance(raw, list) or not raw or int(raw[0]) == 0:
            return []

        rows: list[dict[str, str]] = []
        for index in range(1, len(raw), 2):
            if index + 1 >= len(raw) or not isinstance(raw[index + 1], list):
                break
            fields = raw[index + 1]
            row: dict[str, str] = {}
            for field_index in range(0, len(fields), 2):
                if field_index + 1 >= len(fields):
                    break
                row[self._decode(fields[field_index])] = self._decode(fields[field_index + 1])
            rows.append(row)
        return rows

    def _decode(self, value: Any) -> str:
        """Redis客户端关闭自动解码后，只对文本字段执行UTF-8解码。"""
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    def _require_redis(self) -> Redis:
        """确保initialize已经执行，避免出现难定位的空连接错误。"""
        if self._redis is None:
            raise RuntimeError("RedisSemanticAnswerService尚未初始化")
        return self._redis


def create_semantic_answer_service(settings: Settings) -> SemanticAnswerService:
    """按配置创建真实语义检索或关闭实现。"""
    if settings.semantic_search_enabled:
        return RedisSemanticAnswerService(settings)
    return DisabledSemanticAnswerService()
