from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SemanticAnswerHit:
    """知识库或LangCache的一次有效命中。"""

    answer: str
    provider: str
    distance: float
    source_id: str


@dataclass(frozen=True, slots=True)
class SemanticLookup:
    """一次检索的结果和已生成向量。

    即使命中为空也保留vector_blob，后续统计缺口时不必再次请求Embedding模型。
    """

    hit: SemanticAnswerHit | None = None
    vector_blob: bytes | None = None
    # attempted只在Redis向量查询真正成功执行后为True；关闭或异常不能误报为RAG无命中。
    attempted: bool = False
    failed: bool = False
