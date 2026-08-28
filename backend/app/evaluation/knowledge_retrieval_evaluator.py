from __future__ import annotations

import asyncio
import math
import time
from dataclasses import asdict, dataclass
from statistics import mean
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class KnowledgeRetrievalCase:
    """一条知识召回人工标注样本。

    正样本必须标注目标分片，负样本表示当前知识库不应直接回答的问题。
    评测只检查向量召回，不调用意图模型、回答LLM或业务Tool。
    """

    case_id: str
    text: str
    expected_match: bool
    expected_chunk_no: int | None = None


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    """Redis Search返回的一条未经过距离门槛过滤的候选。"""

    source_id: str
    knowledge_id: int
    version_id: int
    chunk_no: int
    distance: float


@dataclass(frozen=True, slots=True)
class KnowledgeRetrievalResult:
    """单条样本的候选列表与Embedding加检索耗时。"""

    case_id: str
    text: str
    expected_match: bool
    expected_chunk_no: int | None
    candidates: tuple[RetrievalCandidate, ...]
    latency_ms: float
    error_message: str | None = None

    @property
    def top_candidate(self) -> RetrievalCandidate | None:
        """返回距离最近的候选；Redis无结果或调用失败时返回None。"""
        return self.candidates[0] if self.candidates else None


class KnowledgeRetriever(Protocol):
    """评测器依赖的最小向量检索接口，方便单元测试替换真实Redis。"""

    async def retrieve(
        self, question: str, intent: str, top_k: int
    ) -> tuple[RetrievalCandidate, ...]:
        """返回按余弦距离从小到大排列的候选。"""


async def evaluate_knowledge_retrieval(
    cases: list[KnowledgeRetrievalCase],
    retriever: KnowledgeRetriever,
    intent: str,
    top_k: int = 5,
    concurrency: int = 3,
) -> list[KnowledgeRetrievalResult]:
    """并发执行知识召回评测，并保持结果与数据集顺序一致。"""
    if not cases:
        raise ValueError("知识召回评测样本不能为空")
    if top_k < 3:
        raise ValueError("top_k必须大于等于3，才能计算Recall@3")
    if concurrency < 1:
        raise ValueError("concurrency必须大于等于1")

    semaphore = asyncio.Semaphore(concurrency)

    async def evaluate_one(case: KnowledgeRetrievalCase) -> KnowledgeRetrievalResult:
        async with semaphore:
            started_at = time.perf_counter()
            try:
                candidates = await retriever.retrieve(case.text, intent, top_k)
                error_message = None
            except Exception as exc:  # 单条失败必须进入报告，不能中断整个批次。
                candidates = ()
                error_message = f"{type(exc).__name__}: {exc}"
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            return KnowledgeRetrievalResult(
                case_id=case.case_id,
                text=case.text,
                expected_match=case.expected_match,
                expected_chunk_no=case.expected_chunk_no,
                candidates=candidates,
                latency_ms=latency_ms,
                error_message=error_message,
            )

    return list(await asyncio.gather(*(evaluate_one(case) for case in cases)))


def calculate_retrieval_metrics(
    results: list[KnowledgeRetrievalResult],
    target_knowledge_id: int,
    configured_threshold: float,
    threshold_candidates: list[float],
    max_negative_false_positive_rate: float,
) -> dict[str, Any]:
    """计算知识级、分片级和距离门槛级指标。

    Recall@K只判断目标是否出现在候选中；configured recall还要求候选排第一且
    距离通过线上阈值，因此它最接近实际用户是否会拿到这条知识。
    """
    if not results:
        raise ValueError("知识召回评测结果不能为空")
    positives = [result for result in results if result.expected_match]
    negatives = [result for result in results if not result.expected_match]
    if not positives or not negatives:
        raise ValueError("评测集必须同时包含正样本和负样本")

    knowledge_at_1 = sum(
        _is_target(result.top_candidate, target_knowledge_id) for result in positives
    )
    knowledge_at_3 = sum(
        _contains_target(result.candidates[:3], target_knowledge_id)
        for result in positives
    )
    chunk_at_1 = sum(
        _is_expected_chunk(result.top_candidate, target_knowledge_id, result.expected_chunk_no)
        for result in positives
    )
    chunk_at_3 = sum(
        _contains_expected_chunk(
            result.candidates[:3], target_knowledge_id, result.expected_chunk_no
        )
        for result in positives
    )

    configured = _calculate_threshold_row(
        results, target_knowledge_id, configured_threshold
    )
    sweep = [
        _calculate_threshold_row(results, target_knowledge_id, threshold)
        for threshold in sorted(set(threshold_candidates + [configured_threshold]))
    ]
    eligible = [
        row
        for row in sweep
        if row["negative_false_positive_rate"] <= max_negative_false_positive_rate
    ]
    recommended = max(
        eligible or sweep,
        key=lambda row: (
            row["f1"],
            row["positive_recall"],
            -row["negative_false_positive_rate"],
            -row["threshold"],
        ),
    )

    positive_target_distances = sorted(
        distance
        for result in positives
        if (distance := _target_distance(result.candidates, target_knowledge_id))
        is not None
    )
    negative_top_distances = sorted(
        result.top_candidate.distance
        for result in negatives
        if result.top_candidate is not None
    )
    latencies = sorted(result.latency_ms for result in results)
    error_count = sum(result.error_message is not None for result in results)

    return {
        "total_cases": len(results),
        "positive_cases": len(positives),
        "negative_cases": len(negatives),
        "error_count": error_count,
        "knowledge_recall_at_1": _ratio(knowledge_at_1, len(positives)),
        "knowledge_recall_at_3": _ratio(knowledge_at_3, len(positives)),
        "chunk_recall_at_1": _ratio(chunk_at_1, len(positives)),
        "chunk_recall_at_3": _ratio(chunk_at_3, len(positives)),
        "configured_threshold": configured_threshold,
        "configured_threshold_result": configured,
        "threshold_sweep": sweep,
        "recommended_threshold": recommended,
        "positive_target_distance": _distance_summary(positive_target_distances),
        "negative_top_distance": _distance_summary(negative_top_distances),
        "average_latency_ms": round(mean(latencies), 2),
        "p50_latency_ms": _percentile(latencies, 0.50),
        "p95_latency_ms": _percentile(latencies, 0.95),
    }


def evaluate_retrieval_acceptance(
    metrics: dict[str, Any], thresholds: dict[str, Any]
) -> dict[str, Any]:
    """按照数据集声明的生产门槛生成自动验收结果。"""
    specs = (
        ("min_knowledge_recall_at_3", "knowledge_recall_at_3", ">="),
        ("min_chunk_recall_at_3", "chunk_recall_at_3", ">="),
        (
            "min_configured_positive_recall",
            "configured_threshold_result.positive_recall",
            ">=",
        ),
        (
            "max_configured_negative_false_positive_rate",
            "configured_threshold_result.negative_false_positive_rate",
            "<=",
        ),
        ("max_error_count", "error_count", "<="),
    )
    supported = {name for name, _, _ in specs}
    unknown = sorted(set(thresholds) - supported)
    if unknown:
        raise ValueError(f"不支持的知识召回验收门槛：{unknown}")

    checks: list[dict[str, Any]] = []
    for threshold_name, metric_path, operator in specs:
        if threshold_name not in thresholds:
            continue
        actual = float(_nested_value(metrics, metric_path))
        expected = float(thresholds[threshold_name])
        passed = actual >= expected if operator == ">=" else actual <= expected
        checks.append(
            {
                "name": threshold_name,
                "metric": metric_path,
                "operator": operator,
                "expected": expected,
                "actual": round(actual, 6),
                "passed": passed,
            }
        )
    if not checks:
        raise ValueError("acceptance_thresholds至少需要配置一个受支持的门槛")
    return {"passed": all(check["passed"] for check in checks), "checks": checks}


def build_retrieval_report(
    results: list[KnowledgeRetrievalResult],
    metrics: dict[str, Any],
    metadata: dict[str, Any],
    acceptance: dict[str, Any] | None,
) -> dict[str, Any]:
    """组合JSON报告；每条候选保留距离，便于后续人工分析阈值。"""
    return {
        "metadata": metadata,
        "metrics": metrics,
        "acceptance": acceptance,
        "results": [
            {
                **asdict(result),
                "candidates": [asdict(candidate) for candidate in result.candidates],
            }
            for result in results
        ],
    }


def render_retrieval_markdown(report: dict[str, Any]) -> str:
    """生成适合人工审核的知识召回Markdown摘要。"""
    metadata = report["metadata"]
    metrics = report["metrics"]
    configured = metrics["configured_threshold_result"]
    recommended = metrics["recommended_threshold"]
    lines = [
        "# 知识向量召回评测报告",
        "",
        "本报告只调用Embedding与Redis Search，不调用意图模型、回答LLM或Tool。",
        "",
        "## 运行信息",
        "",
        f"- 运行时间：{metadata['generated_at']}",
        f"- 数据集：{metadata['dataset']}",
        f"- 目标知识：{metadata['target_title']}",
        f"- 知识ID：{metadata['target_knowledge_id']}",
        f"- Embedding模型：{metadata['embedding_model']}",
        f"- 样本数：{metrics['total_cases']}（正样本{metrics['positive_cases']}，负样本{metrics['negative_cases']}）",
        "",
        "## 核心指标",
        "",
        f"- 知识 Recall@1：{_percent(metrics['knowledge_recall_at_1'])}",
        f"- 知识 Recall@3：{_percent(metrics['knowledge_recall_at_3'])}",
        f"- 分片 Recall@1：{_percent(metrics['chunk_recall_at_1'])}",
        f"- 分片 Recall@3：{_percent(metrics['chunk_recall_at_3'])}",
        f"- 当前阈值：{metrics['configured_threshold']:.3f}",
        f"- 当前阈值正样本召回率：{_percent(configured['positive_recall'])}",
        f"- 当前阈值负样本误命中率：{_percent(configured['negative_false_positive_rate'])}",
        f"- 建议候选阈值：{recommended['threshold']:.3f}",
        f"- 建议阈值正样本召回率：{_percent(recommended['positive_recall'])}",
        f"- 建议阈值负样本误命中率：{_percent(recommended['negative_false_positive_rate'])}",
        f"- 平均耗时：{metrics['average_latency_ms']} ms",
        f"- P95耗时：{metrics['p95_latency_ms']} ms",
        f"- 调用错误数：{metrics['error_count']}",
        "",
        "## 阈值扫描",
        "",
        "| 阈值 | 正样本召回率 | 负样本误命中率 | 精确率 | F1 | 总体准确率 |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in metrics["threshold_sweep"]:
        lines.append(
            f"| {row['threshold']:.3f} | {_percent(row['positive_recall'])} | "
            f"{_percent(row['negative_false_positive_rate'])} | "
            f"{_percent(row['precision'])} | {_percent(row['f1'])} | "
            f"{_percent(row['accuracy'])} |"
        )

    acceptance = report.get("acceptance")
    if acceptance:
        lines.extend(
            [
                "",
                "## 自动验收",
                "",
                f"- 总结：{'通过' if acceptance['passed'] else '未通过'}",
                "",
                "| 门槛 | 实际值 | 要求 | 结果 |",
                "| --- | ---: | ---: | --- |",
            ]
        )
        for check in acceptance["checks"]:
            lines.append(
                f"| {check['name']} | {check['actual']} | "
                f"{check['operator']} {check['expected']} | "
                f"{'通过' if check['passed'] else '未通过'} |"
            )

    lines.extend(
        [
            "",
            "## 样本明细",
            "",
            "| ID | 类型 | 期望分片 | Top1来源 | Top1分片 | 距离 | 耗时(ms) |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report["results"]:
        top = row["candidates"][0] if row["candidates"] else None
        lines.append(
            f"| {row['case_id']} | {'正' if row['expected_match'] else '负'} | "
            f"{row['expected_chunk_no'] if row['expected_chunk_no'] is not None else '-'} | "
            f"{top['knowledge_id'] if top else '-'} | "
            f"{top['chunk_no'] if top else '-'} | "
            f"{top['distance']:.6f} | {row['latency_ms']} |"
            if top
            else f"| {row['case_id']} | {'正' if row['expected_match'] else '负'} | "
            f"{row['expected_chunk_no'] if row['expected_chunk_no'] is not None else '-'} | - | - | - | {row['latency_ms']} |"
        )
    return "\n".join(lines) + "\n"


def _calculate_threshold_row(
    results: list[KnowledgeRetrievalResult],
    target_knowledge_id: int,
    threshold: float,
) -> dict[str, Any]:
    """模拟线上只采用Top1且按距离门槛决定是否返回的行为。"""
    positives = [result for result in results if result.expected_match]
    negatives = [result for result in results if not result.expected_match]
    accepted = [
        result
        for result in results
        if result.top_candidate is not None and result.top_candidate.distance <= threshold
    ]
    correct_positive = sum(
        result.top_candidate is not None
        and result.top_candidate.distance <= threshold
        and _is_target(result.top_candidate, target_knowledge_id)
        for result in positives
    )
    negative_false_positive = sum(
        result.top_candidate is not None and result.top_candidate.distance <= threshold
        for result in negatives
    )
    negative_rejected = len(negatives) - negative_false_positive
    precision = _ratio(correct_positive, len(accepted))
    recall = _ratio(correct_positive, len(positives))
    f1 = (
        round(2 * precision * recall / (precision + recall), 6)
        if precision + recall
        else 0.0
    )
    return {
        "threshold": round(float(threshold), 6),
        "accepted_cases": len(accepted),
        "correct_positive": correct_positive,
        "positive_recall": recall,
        "negative_false_positive": negative_false_positive,
        "negative_false_positive_rate": _ratio(
            negative_false_positive, len(negatives)
        ),
        "negative_rejection_rate": _ratio(negative_rejected, len(negatives)),
        "precision": precision,
        "f1": f1,
        "accuracy": _ratio(correct_positive + negative_rejected, len(results)),
    }


def _is_target(
    candidate: RetrievalCandidate | None, target_knowledge_id: int
) -> bool:
    return candidate is not None and candidate.knowledge_id == target_knowledge_id


def _contains_target(
    candidates: tuple[RetrievalCandidate, ...], target_knowledge_id: int
) -> bool:
    return any(candidate.knowledge_id == target_knowledge_id for candidate in candidates)


def _is_expected_chunk(
    candidate: RetrievalCandidate | None,
    target_knowledge_id: int,
    expected_chunk_no: int | None,
) -> bool:
    return (
        candidate is not None
        and expected_chunk_no is not None
        and candidate.knowledge_id == target_knowledge_id
        and candidate.chunk_no == expected_chunk_no
    )


def _contains_expected_chunk(
    candidates: tuple[RetrievalCandidate, ...],
    target_knowledge_id: int,
    expected_chunk_no: int | None,
) -> bool:
    return any(
        _is_expected_chunk(candidate, target_knowledge_id, expected_chunk_no)
        for candidate in candidates
    )


def _target_distance(
    candidates: tuple[RetrievalCandidate, ...], target_knowledge_id: int
) -> float | None:
    return next(
        (
            candidate.distance
            for candidate in candidates
            if candidate.knowledge_id == target_knowledge_id
        ),
        None,
    )


def _distance_summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "p50": None, "p95": None, "max": None}
    return {
        "count": len(values),
        "min": round(values[0], 6),
        "p50": _percentile(values, 0.50, digits=6),
        "p95": _percentile(values, 0.95, digits=6),
        "max": round(values[-1], 6),
    }


def _nested_value(values: dict[str, Any], path: str) -> Any:
    current: Any = values
    for part in path.split("."):
        current = current[part]
    return current


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _percentile(
    sorted_values: list[float], percentile: float, digits: int = 2
) -> float:
    if not sorted_values:
        return 0.0
    index = max(0, math.ceil(percentile * len(sorted_values)) - 1)
    return round(sorted_values[index], digits)


def _percent(value: float) -> str:
    return f"{value * 100:.2f}%"
