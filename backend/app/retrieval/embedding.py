from __future__ import annotations

import asyncio
import sys
from array import array
from typing import Any

import httpx

from app.config import Settings


class DoubaoEmbeddingClient:
    """调用豆包Embedding接口生成文本向量。

    vision系列使用多模态接口，large-text/text系列使用文本接口。
    两类模型的请求格式不同，不能只替换模型名而复用同一个HTTP路径。
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.embedding_base_url.rstrip("/"),
            timeout=settings.embedding_timeout_seconds,
        )

    async def embed(self, text: str) -> list[float]:
        """把一段文本转换为固定维度的浮点向量。"""
        if not text.strip():
            raise ValueError("Embedding文本不能为空")

        endpoint, payload = self._build_request(text)
        headers = {"Authorization": f"Bearer {self.settings.embedding_api_key}"}

        # 同时限制HTTP请求和整个异步调用，Windows与Linux的超时行为保持一致。
        async with asyncio.timeout(self.settings.embedding_timeout_seconds):
            response = await self._client.post(
                endpoint,
                headers=headers,
                json=payload,
            )
        response.raise_for_status()
        vector = self._extract_vector(response.json())
        if len(vector) != self.settings.embedding_dimension:
            raise ValueError(
                "Embedding维度与配置不一致："
                f"expected={self.settings.embedding_dimension}, actual={len(vector)}"
            )
        return vector

    def _build_request(self, text: str) -> tuple[str, dict[str, Any]]:
        """根据模型类型构造对应的接口路径和请求体。"""
        model = self.settings.embedding_model
        if "vision" in model.lower():
            return "/embeddings/multimodal", {
                "model": model,
                "input": [{"type": "text", "text": text}],
                "encoding_format": "float",
            }
        return "/embeddings", {
            "model": model,
            "input": [text],
            "encoding_format": "float",
            # 固定为Redis索引配置的维度，避免查询向量和索引维度不一致。
            "dimensions": self.settings.embedding_dimension,
        }

    async def close(self) -> None:
        """释放httpx连接池。"""
        await self._client.aclose()

    def _extract_vector(self, payload: dict[str, Any]) -> list[float]:
        """兼容data为对象或列表的响应形式，并严格校验向量内容。"""
        raw_data = payload.get("data")
        item = raw_data[0] if isinstance(raw_data, list) and raw_data else raw_data
        raw_vector = item.get("embedding") if isinstance(item, dict) else None

        # 少数多模态响应会把单个向量再包一层列表，这里只解一层。
        if (
            isinstance(raw_vector, list)
            and len(raw_vector) == 1
            and isinstance(raw_vector[0], list)
        ):
            raw_vector = raw_vector[0]
        if not isinstance(raw_vector, list) or not raw_vector:
            raise ValueError("Embedding接口没有返回有效向量")
        return [float(value) for value in raw_vector]


def vector_to_bytes(vector: list[float]) -> bytes:
    """转换成Redis Search需要的FLOAT32小端字节串。

    x86 Windows与Linux都是小端序。显式处理字节序，可以防止将来更换CPU架构后
    Redis错误解析向量。
    """
    values = array("f", vector)
    if sys.byteorder != "little":
        values.byteswap()
    return values.tobytes()
