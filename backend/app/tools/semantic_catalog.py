from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.config import Settings
from app.retrieval.embedding import DoubaoEmbeddingClient, vector_to_bytes


logger = logging.getLogger("smart_customer_service.tool_retrieval")
_INTERNAL_ARGUMENTS = {"sessionId", "userId", "requestId"}


class RedisToolSemanticCatalog:
    """使用 Redis Search 保存并召回 MCP Tool 的语义向量。

    这个组件只负责缩小候选工具范围，不直接决定或调用 Tool。最终工具选择、
    参数提取和组合知识检索仍由理解模型完成，因此召回失败时可以安全回退到完整目录。
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._redis: Redis | None = None
        self._embedding = DoubaoEmbeddingClient(settings)
        self.ready = False
        self.error: str | None = None

    async def initialize(self, catalog: list[dict[str, Any]]) -> None:
        """创建索引，并只为新增或内容发生变化的 Tool 重新生成向量。"""
        if not self.settings.tool_retrieval_enabled:
            return
        if not self.settings.has_real_embedding_api_key:
            raise RuntimeError("已启用 Tool 语义召回，但没有配置真实 EMBEDDING_API_KEY")

        self._redis = Redis.from_url(
            self.settings.redis_url,
            decode_responses=False,
            health_check_interval=30,
            socket_connect_timeout=5,
            socket_timeout=8,
            retry_on_timeout=True,
        )
        await self._redis.ping()
        await self._ensure_index()
        await self._synchronize_catalog(catalog)
        self.ready = True
        self.error = None
        logger.info("MCP Tool 向量目录已就绪: tools=%s", len(catalog))

    async def candidate_names(self, message: str) -> list[str] | None:
        """返回按余弦距离排序的候选 Tool；不可用时返回 None 触发完整目录降级。"""
        if not self.ready or not message.strip():
            return None

        try:
            # 前置召回必须有严格超时，否则优化步骤本身可能比 LLM 路由更慢。
            async with asyncio.timeout(self.settings.tool_retrieval_timeout_seconds):
                vector = await self._embedding.embed(message)
                raw = await self._require_redis().execute_command(
                    "FT.SEARCH",
                    self.settings.tool_retrieval_index_name,
                    f"(*)=>[KNN {self.settings.tool_retrieval_top_k} "
                    "@embedding $vector AS vector_distance]",
                    "PARAMS",
                    "2",
                    "vector",
                    vector_to_bytes(vector),
                    "SORTBY",
                    "vector_distance",
                    "ASC",
                    "RETURN",
                    "2",
                    "name",
                    "vector_distance",
                    "DIALECT",
                    "2",
                )
            rows = self._parse_search_rows(raw)
            names = [
                row["name"]
                for row in rows
                if row.get("name")
                and float(row.get("vector_distance", "1"))
                <= self.settings.tool_retrieval_max_distance
            ]
            # 距离全部超限时不勉强使用错误候选，交给完整目录保证召回率。
            return names or None
        except Exception as exc:
            self.error = exc.__class__.__name__
            logger.warning("Tool 语义召回失败，已回退完整目录: error=%s", self.error)
            return None

    async def close(self) -> None:
        """释放 Embedding HTTP 客户端和 Redis 连接。"""
        await self._embedding.close()
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
        self.ready = False

    async def _synchronize_catalog(self, catalog: list[dict[str, Any]]) -> None:
        """按内容哈希增量同步目录，并清理 Nacos/MCP 中已经删除的 Tool。"""
        client = self._require_redis()
        active_keys: set[str] = set()
        for tool in catalog:
            name = str(tool.get("name") or "").strip()
            if not name:
                continue
            key = f"{self.settings.tool_retrieval_key_prefix}{name}"
            active_keys.add(key)
            retrieval_text = self._build_retrieval_text(tool)
            content_hash = hashlib.sha256(
                f"{self.settings.embedding_model}\n{retrieval_text}".encode("utf-8")
            ).hexdigest()
            current_hash = await client.hget(key, "content_hash")
            if self._decode(current_hash) == content_hash:
                continue

            vector = await self._embedding.embed(retrieval_text)
            await client.hset(
                key,
                mapping={
                    "name": name,
                    "content": retrieval_text,
                    "content_hash": content_hash,
                    "embedding_model": self.settings.embedding_model,
                    "updated_at": int(time.time()),
                    "embedding": vector_to_bytes(vector),
                },
            )

        async for raw_key in client.scan_iter(
            match=f"{self.settings.tool_retrieval_key_prefix}*"
        ):
            key = self._decode(raw_key)
            if key and key not in active_keys:
                await client.delete(raw_key)

    async def _ensure_index(self) -> None:
        """创建独立 Tool 向量索引，避免与知识库和 LangCache 数据混用。"""
        command: list[Any] = [
            "FT.CREATE",
            self.settings.tool_retrieval_index_name,
            "ON",
            "HASH",
            "PREFIX",
            "1",
            self.settings.tool_retrieval_key_prefix,
            "SCHEMA",
            "name",
            "TAG",
            "content",
            "TEXT",
            "content_hash",
            "TAG",
            "embedding_model",
            "TAG",
            "updated_at",
            "NUMERIC",
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

    @staticmethod
    def _build_retrieval_text(tool: dict[str, Any]) -> str:
        """提取适合语义召回的名称、用途和用户参数说明，不包含内部身份参数。"""
        name = str(tool.get("name") or "").strip()
        description = str(tool.get("description") or "").strip()
        schema = tool.get("input_schema")
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        parameter_lines: list[str] = []
        for parameter_name, raw_definition in properties.items():
            if parameter_name in _INTERNAL_ARGUMENTS:
                continue
            definition = raw_definition if isinstance(raw_definition, dict) else {}
            parameter_description = str(definition.get("description") or "").strip()
            enum_values = definition.get("enum")
            enum_text = (
                f"，可选值：{', '.join(str(value) for value in enum_values)}"
                if isinstance(enum_values, list) and enum_values
                else ""
            )
            parameter_lines.append(
                f"{parameter_name}：{parameter_description}{enum_text}".rstrip("：")
            )
        parameters = "；".join(parameter_lines)
        return f"工具名称：{name}\n工具用途：{description}\n业务参数：{parameters}".strip()

    @classmethod
    def _parse_search_rows(cls, raw: Any) -> list[dict[str, str]]:
        """把 redis-py 的 FT.SEARCH 数组响应转换为普通字典列表。"""
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
                row[cls._decode(fields[field_index])] = cls._decode(
                    fields[field_index + 1]
                )
            rows.append(row)
        return rows

    @staticmethod
    def _decode(value: Any) -> str:
        """只在 Redis 返回字节串时执行 UTF-8 解码。"""
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return "" if value is None else str(value)

    def _require_redis(self) -> Redis:
        """确保调用发生在初始化之后。"""
        if self._redis is None:
            raise RuntimeError("Redis Tool 语义目录尚未初始化")
        return self._redis
