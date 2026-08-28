from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？；!?;])")


@dataclass(frozen=True, slots=True)
class TextChunk:
    """切片器内部使用的稳定文本分片。"""

    chunk_no: int
    content: str
    content_hash: str
    questions: tuple[str, ...] = ()


class KnowledgeTextSplitter:
    """适合中文FAQ和规则文本的统一服务端切片器。

    优先保留段落和完整句子，只有单句超过上限时才按字符硬切。
    overlap让跨片段的条件和结论仍保留少量上下文。
    """

    def __init__(self, target_size: int = 450, max_size: int = 700, overlap: int = 60):
        if not 0 <= overlap < target_size <= max_size:
            raise ValueError("切片参数必须满足0 <= overlap < target_size <= max_size")
        self.target_size = target_size
        self.max_size = max_size
        self.overlap = overlap

    def split(self, content: str) -> list[TextChunk]:
        normalized = re.sub(r"\r\n?", "\n", content).strip()
        if not normalized:
            raise ValueError("知识正文不能为空")
        if len(normalized) <= self.max_size:
            return [self._chunk(0, normalized)]

        units: list[str] = []
        for paragraph in re.split(r"\n\s*\n|\n", normalized):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            units.extend(self._split_long_unit(paragraph))

        chunks: list[str] = []
        current = ""
        for unit in units:
            separator = "\n" if current else ""
            if current and len(current) + len(separator) + len(unit) > self.target_size:
                chunks.append(current)
                prefix = current[-self.overlap :] if self.overlap else ""
                current = f"{prefix}\n{unit}".strip()
            else:
                current = f"{current}{separator}{unit}"
            if len(current) > self.max_size:
                hard_parts = self._hard_split(current)
                chunks.extend(hard_parts[:-1])
                current = hard_parts[-1]
        if current:
            chunks.append(current)

        # 内容相同的片段只保留一次，防止重叠造成重复召回。
        unique: list[str] = []
        seen: set[str] = set()
        for value in chunks:
            value = value.strip()
            digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
            if value and digest not in seen:
                seen.add(digest)
                unique.append(value)
        return [self._chunk(index, value) for index, value in enumerate(unique)]

    def _split_long_unit(self, value: str) -> list[str]:
        if len(value) <= self.max_size:
            return [value]
        sentences = [part.strip() for part in _SENTENCE_BOUNDARY.split(value) if part.strip()]
        if len(sentences) == 1:
            return self._hard_split(value)
        result: list[str] = []
        current = ""
        for sentence in sentences:
            if current and len(current) + len(sentence) > self.target_size:
                result.append(current)
                current = sentence
            else:
                current += sentence
        if current:
            result.append(current)
        return result

    def _hard_split(self, value: str) -> list[str]:
        step = self.max_size - self.overlap
        return [value[index : index + self.max_size] for index in range(0, len(value), step)]

    @staticmethod
    def _chunk(index: int, value: str) -> TextChunk:
        return TextChunk(
            chunk_no=index,
            content=value,
            content_hash=hashlib.sha256(value.encode("utf-8")).hexdigest(),
        )


class KnowledgeSplitRequest(BaseModel):
    """知识管理页面提交给Python的原始正文。"""

    content: str = Field(min_length=1, max_length=70000)


class KnowledgeSplitChunk(BaseModel):
    chunk_no: int
    content: str


class KnowledgeSplitResponse(BaseModel):
    chunks: list[KnowledgeSplitChunk]


def create_knowledge_chunk_router() -> APIRouter:
    """创建统一的服务端知识切片接口。"""
    router = APIRouter(prefix="/api/knowledge/chunks", tags=["knowledge-chunks"])
    splitter = KnowledgeTextSplitter()

    @router.post("/split", response_model=KnowledgeSplitResponse)
    async def split_knowledge_content(
        payload: KnowledgeSplitRequest,
    ) -> KnowledgeSplitResponse:
        try:
            chunks = splitter.split(payload.content)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if len(chunks) > 100:
            raise HTTPException(status_code=422, detail="正文切分后超过100个分片，请缩短内容")
        return KnowledgeSplitResponse(
            chunks=[
                KnowledgeSplitChunk(chunk_no=chunk.chunk_no, content=chunk.content)
                for chunk in chunks
            ]
        )

    return router
