from __future__ import annotations

import asyncio
import hmac
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from app.config import Settings
from app.retrieval.embedding import DoubaoEmbeddingClient, vector_to_bytes
from app.retrieval.knowledge_publisher import (
    KnowledgeDeleteRequest,
    KnowledgePublishRequest,
    RedisKnowledgePublisher,
)


class ReleaseEvaluationCase(BaseModel):
    case_id: int = Field(gt=0)
    question: str = Field(min_length=1, max_length=2000)
    expected_intent: str = Field(min_length=1, max_length=64)
    expected_match: bool = True


class ReleaseEvaluationRequest(BaseModel):
    run_id: int = Field(gt=0)
    knowledge: KnowledgePublishRequest
    cases: list[ReleaseEvaluationCase] = Field(min_length=3, max_length=100)


class ReleaseCaseResult(BaseModel):
    case_id: int
    question: str
    expected_match: bool = True
    passed_at_1: bool
    passed_at_3: bool
    passed_threshold: bool
    top_knowledge_id: int | None
    top_version_id: int | None
    top_chunk_no: int | None
    top_distance: float | None
    latency_ms: float
    error_message: str | None = None


class ReleaseEvaluationResponse(BaseModel):
    run_id: int
    passed: bool
    total_cases: int
    recall_at_1: float
    recall_at_3: float
    threshold_recall: float
    positive_cases: int
    hard_negative_cases: int
    hard_negative_false_positive_rate: float
    error_count: int
    average_latency_ms: float
    p95_latency_ms: float
    distance_threshold: float
    cases: list[ReleaseCaseResult]


@dataclass(frozen=True, slots=True)
class _Candidate:
    knowledge_id: int
    version_id: int
    chunk_no: int
    distance: float


class ReleaseGateEvaluator:
    """在真实知识索引中临时发布testing文档并执行候选版本召回验收。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def evaluate(
        self, payload: ReleaseEvaluationRequest
    ) -> ReleaseEvaluationResponse:
        if not self.settings.semantic_search_enabled:
            raise RuntimeError("知识发布门禁要求启用Redis Search")
        if not self.settings.has_real_embedding_api_key:
            raise RuntimeError("知识发布门禁没有可用的Embedding模型")

        publisher = RedisKnowledgePublisher(self.settings)
        embedding = DoubaoEmbeddingClient(self.settings)
        redis = Redis.from_url(self.settings.redis_url, decode_responses=False)
        await publisher.initialize()
        try:
            # 测试状态不会被线上客服召回；finally无论成功失败都会清理临时键。
            # 发布验收验证的是检索质量，不应因为业务计划生效时间尚未到达而跳过候选知识。
            # testing 文档不会被线上只查询 approved 状态的客服召回，并且会在 finally 中删除。
            testing = payload.knowledge.model_copy(update={
                "index_status": "testing",
                "effective_at": datetime.now(timezone.utc) - timedelta(seconds=1),
                "expired_at": None,
            })
            published = await publisher.publish(testing)
            if not published.chunks:
                raise ValueError("候选知识当前不在生效时间范围内，无法执行发布验收")
            semaphore = asyncio.Semaphore(self.settings.release_evaluation_concurrency)

            async def evaluate_one(item: ReleaseEvaluationCase) -> ReleaseCaseResult:
                async with semaphore:
                    started = time.perf_counter()
                    try:
                        vector = vector_to_bytes(await embedding.embed(item.question))
                        candidates = await self._search(
                            redis, vector, item.expected_intent,
                            self.settings.release_evaluation_top_k,
                        )
                        top = candidates[0] if candidates else None
                        target = payload.knowledge.knowledge_id
                        target_at_1 = top is not None and top.knowledge_id == target
                        target_at_3 = any(
                            candidate.knowledge_id == target for candidate in candidates[:3]
                        )
                        target_distance = next(
                            (candidate.distance for candidate in candidates
                             if candidate.knowledge_id == target),
                            None,
                        )
                        target_within_threshold = (
                            target_at_1
                            and top is not None
                            and top.distance <= self.settings.knowledge_distance_threshold
                        )
                        # 正样本要求召回候选知识；困难负样本恰好相反，不能误召回候选知识。
                        passed_at_1 = (
                            target_at_1 if item.expected_match else not target_at_1
                        )
                        passed_at_3 = (
                            target_at_3 if item.expected_match else not target_at_3
                        )
                        passed_threshold = (
                            target_within_threshold
                            if item.expected_match else not target_within_threshold
                        )
                        error_message = None
                    except Exception as exc:
                        top = None
                        passed_at_1 = passed_at_3 = passed_threshold = False
                        target_distance = None
                        error_message = f"{type(exc).__name__}: {exc}"[:1000]
                    return ReleaseCaseResult(
                        case_id=item.case_id,
                        question=item.question,
                        expected_match=item.expected_match,
                        passed_at_1=passed_at_1,
                        passed_at_3=passed_at_3,
                        passed_threshold=passed_threshold,
                        top_knowledge_id=top.knowledge_id if top else None,
                        top_version_id=top.version_id if top else None,
                        top_chunk_no=top.chunk_no if top else None,
                        top_distance=(
                            round(target_distance, 6) if target_distance is not None else None
                        ),
                        latency_ms=round((time.perf_counter() - started) * 1000, 2),
                        error_message=error_message,
                    )

            results = list(await asyncio.gather(
                *(evaluate_one(item) for item in payload.cases)
            ))
            return calculate_release_acceptance(payload.run_id, results, self.settings)
        finally:
            try:
                await publisher.delete(KnowledgeDeleteRequest(
                    knowledge_id=payload.knowledge.knowledge_id,
                    knowledge_code=payload.knowledge.knowledge_code,
                ))
            finally:
                await embedding.close()
                await publisher.close()
                await redis.aclose()

    async def _search(
        self,
        redis: Redis,
        vector: bytes,
        intent: str,
        top_k: int,
    ) -> tuple[_Candidate, ...]:
        query = (
            f"(@intent:{{{intent}}} @status:{{approved|testing}})"
            f"=>[KNN {top_k} @embedding $vector AS vector_distance]"
        )
        raw = await redis.execute_command(
            "FT.SEARCH", self.settings.knowledge_index_name, query,
            "PARAMS", "2", "vector", vector,
            "SORTBY", "vector_distance", "ASC",
            "RETURN", "5", "knowledge_id", "version_id", "chunk_no",
            "id", "vector_distance", "DIALECT", "2",
        )
        candidates: list[_Candidate] = []
        for index in range(1, len(raw), 2):
            fields = raw[index + 1]
            values = {
                self._decode(fields[offset]): self._decode(fields[offset + 1])
                for offset in range(0, len(fields), 2)
            }
            source = values.get("id", "").split(":")
            candidates.append(_Candidate(
                knowledge_id=int(values.get("knowledge_id") or source[0]),
                version_id=int(values.get("version_id") or source[1]),
                chunk_no=int(values.get("chunk_no") or source[2]),
                distance=float(values["vector_distance"]),
            ))
        return tuple(candidates)

    @staticmethod
    def _decode(value: Any) -> str:
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def calculate_release_acceptance(
    run_id: int,
    results: list[ReleaseCaseResult],
    settings: Settings,
) -> ReleaseEvaluationResponse:
    """根据固定生产门槛计算结果；所有单条异常都会导致本次验收失败。"""
    if not results:
        raise ValueError("发布验收测试用例不能为空")
    total = len(results)
    positives = [item for item in results if item.expected_match]
    negatives = [item for item in results if not item.expected_match]
    if not positives:
        raise ValueError("发布验收至少需要一条正样本")
    recall_at_1 = round(sum(item.passed_at_1 for item in positives) / len(positives), 6)
    recall_at_3 = round(sum(item.passed_at_3 for item in positives) / len(positives), 6)
    threshold_recall = round(
        sum(item.passed_threshold for item in positives) / len(positives), 6
    )
    hard_negative_false_positive_rate = round(
        sum(not item.passed_threshold for item in negatives) / len(negatives), 6
    ) if negatives else 0.0
    error_count = sum(item.error_message is not None for item in results)
    latencies = sorted(item.latency_ms for item in results)
    p95_index = max(0, (95 * len(latencies) + 99) // 100 - 1)
    passed = (
        error_count == 0
        and recall_at_1 >= settings.release_min_recall_at_1
        and recall_at_3 >= settings.release_min_recall_at_3
        and threshold_recall >= settings.release_min_threshold_recall
        and hard_negative_false_positive_rate
        <= settings.release_max_hard_negative_false_positive_rate
    )
    return ReleaseEvaluationResponse(
        run_id=run_id,
        passed=passed,
        total_cases=total,
        recall_at_1=recall_at_1,
        recall_at_3=recall_at_3,
        threshold_recall=threshold_recall,
        positive_cases=len(positives),
        hard_negative_cases=len(negatives),
        hard_negative_false_positive_rate=hard_negative_false_positive_rate,
        error_count=error_count,
        average_latency_ms=round(mean(latencies), 2),
        p95_latency_ms=round(latencies[p95_index], 2),
        distance_threshold=settings.knowledge_distance_threshold,
        cases=results,
    )


def create_release_evaluation_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/internal/evaluation", tags=["release-evaluation"])
    evaluator = ReleaseGateEvaluator(settings)

    @router.post("/knowledge", response_model=ReleaseEvaluationResponse)
    async def evaluate_knowledge(
        payload: ReleaseEvaluationRequest,
        x_internal_token: str = Header(default="", alias="X-Internal-Token"),
    ) -> ReleaseEvaluationResponse:
        expected = settings.business_tool_internal_token
        if not expected or not hmac.compare_digest(x_internal_token, expected):
            raise HTTPException(status_code=401, detail="内部调用身份校验失败")
        try:
            return await evaluator.evaluate(payload)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return router
