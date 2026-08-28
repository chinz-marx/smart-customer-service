from __future__ import annotations

import asyncio
import math
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from statistics import mean
from typing import Any

from app.schemas import ChatHistoryItem
from app.understanding.service import UnderstandingService


@dataclass(frozen=True, slots=True)
class IntentEvaluationCase:
    """一条人工标注意图样本。

    expected_slots只记录用户明确给出的槽位。history和current_intent用于模拟
    多轮会话，但评测器仍然只调用语义理解服务，不会进入编排器或调用Tool。
    """

    case_id: str
    text: str
    expected_intent: str
    expected_slots: dict[str, str] = field(default_factory=dict)
    history: tuple[ChatHistoryItem, ...] = ()
    current_intent: str | None = None
    current_slots: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IntentEvaluationResult:
    """单条样本的识别结果、上下文和耗时。"""

    case_id: str
    text: str
    expected_intent: str
    predicted_intent: str
    confidence: float
    expected_slots: dict[str, str]
    predicted_slots: dict[str, str]
    source: str
    latency_ms: float
    error_message: str | None = None
    current_intent: str | None = None

    @property
    def intent_correct(self) -> bool:
        """判断意图是否完全匹配人工标注。"""
        return self.expected_intent == self.predicted_intent

    @property
    def slots_exact(self) -> bool:
        """对有槽位标注的样本执行严格字典匹配，包括多余槽位。"""
        return self.expected_slots == self.predicted_slots


async def evaluate_intents(
    cases: list[IntentEvaluationCase],
    service: UnderstandingService,
    concurrency: int = 4,
) -> list[IntentEvaluationResult]:
    """并发执行意图检测，但不进入编排器，也不会调用任何Tool。

    每条样本的计时从获得并发许可后开始，因此排队时间不会污染模型识别耗时。
    """
    if concurrency < 1:
        raise ValueError("concurrency必须大于等于1")

    semaphore = asyncio.Semaphore(concurrency)

    async def evaluate_one(case: IntentEvaluationCase) -> IntentEvaluationResult:
        async with semaphore:
            started_at = time.perf_counter()
            result = await service.understand(
                message=case.text,
                history=list(case.history),
                current_intent=case.current_intent,
                current_slots=case.current_slots,
            )
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            return IntentEvaluationResult(
                case_id=case.case_id,
                text=case.text,
                expected_intent=case.expected_intent,
                predicted_intent=result.intent,
                confidence=result.confidence,
                expected_slots=case.expected_slots,
                predicted_slots=result.slots,
                source=result.source,
                latency_ms=latency_ms,
                error_message=result.error_message,
                current_intent=case.current_intent,
            )

    # gather保持输入顺序，报告中的失败案例可以与数据集稳定对应。
    return list(await asyncio.gather(*(evaluate_one(case) for case in cases)))


def calculate_metrics(
    results: list[IntentEvaluationResult],
    tool_intents: set[str],
) -> dict[str, Any]:
    """计算意图检测指标，不执行真实Tool。

    “潜在错误Tool路由”表示错误预测成某个Tool意图的次数；实际Tool调用固定为0。
    """
    if not results:
        raise ValueError("评测结果不能为空")

    total = len(results)
    correct = sum(result.intent_correct for result in results)
    unknown_rows = [result for result in results if result.expected_intent == "unknown"]
    unknown_correct = sum(result.predicted_intent == "unknown" for result in unknown_rows)

    slot_rows = [result for result in results if result.expected_slots]
    slot_exact = sum(result.slots_exact for result in slot_rows)

    potential_wrong_tool_routes = sum(
        result.predicted_intent in tool_intents
        and result.predicted_intent != result.expected_intent
        for result in results
    )
    fallback_count = sum(result.source == "keyword" for result in results)
    llm_error_count = sum(result.source == "llm-error" for result in results)
    latencies = sorted(result.latency_ms for result in results)

    expected_counts = Counter(result.expected_intent for result in results)
    correct_counts = Counter(
        result.expected_intent for result in results if result.intent_correct
    )
    per_intent = {
        intent: {
            "total": count,
            "correct": correct_counts[intent],
            "accuracy": _ratio(correct_counts[intent], count),
        }
        for intent, count in sorted(expected_counts.items())
    }

    confusion: dict[str, dict[str, int]] = defaultdict(dict)
    raw_confusion: dict[str, Counter[str]] = defaultdict(Counter)
    for result in results:
        raw_confusion[result.expected_intent][result.predicted_intent] += 1
    for expected, predictions in sorted(raw_confusion.items()):
        confusion[expected] = dict(sorted(predictions.items()))

    return {
        "total_cases": total,
        "intent_correct": correct,
        "intent_accuracy": _ratio(correct, total),
        "slot_annotated_cases": len(slot_rows),
        "slot_exact_correct": slot_exact,
        "slot_accuracy": _ratio(slot_exact, len(slot_rows)),
        "unknown_cases": len(unknown_rows),
        "unknown_correct": unknown_correct,
        "unknown_recall": _ratio(unknown_correct, len(unknown_rows)),
        "actual_tool_calls": 0,
        "potential_wrong_tool_routes": potential_wrong_tool_routes,
        "llm_fallback_count": fallback_count,
        "llm_fallback_rate": _ratio(fallback_count, total),
        "llm_error_count": llm_error_count,
        "average_latency_ms": round(mean(latencies), 2),
        "p50_latency_ms": _percentile(latencies, 0.50),
        "p95_latency_ms": _percentile(latencies, 0.95),
        "source_counts": dict(sorted(Counter(result.source for result in results).items())),
        "per_intent": per_intent,
        "confusion_matrix": dict(confusion),
    }


def evaluate_acceptance_thresholds(
    metrics: dict[str, Any],
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    """根据数据集声明的门槛自动判断本次意图评测是否可以通过。

    门槛名称显式列在这里，拼写错误不会被静默忽略。每项结果都会进入JSON和
    Markdown报告，CI或人工执行时可以直接看到是哪一项没有达标。
    """
    metric_specs = (
        ("min_intent_accuracy", "intent_accuracy", ">="),
        ("min_unknown_recall", "unknown_recall", ">="),
        ("min_per_intent_accuracy", "per_intent_accuracy", ">="),
        ("max_potential_wrong_tool_routes", "potential_wrong_tool_routes", "<="),
        ("max_llm_fallback_rate", "llm_fallback_rate", "<="),
        ("max_llm_error_count", "llm_error_count", "<="),
        ("max_average_latency_ms", "average_latency_ms", "<="),
    )
    supported_names = {item[0] for item in metric_specs}
    unknown_names = sorted(set(thresholds) - supported_names)
    if unknown_names:
        raise ValueError(f"不支持的验收门槛：{unknown_names}")

    checks: list[dict[str, Any]] = []
    for threshold_name, metric_name, operator in metric_specs:
        if threshold_name not in thresholds:
            continue
        expected = float(thresholds[threshold_name])
        if metric_name == "per_intent_accuracy":
            actual = min(
                row["accuracy"] for row in metrics["per_intent"].values()
            )
        else:
            actual = float(metrics[metric_name])
        passed = actual >= expected if operator == ">=" else actual <= expected
        checks.append(
            {
                "name": threshold_name,
                "metric": metric_name,
                "operator": operator,
                "expected": expected,
                "actual": round(actual, 6),
                "passed": passed,
            }
        )

    if not checks:
        raise ValueError("acceptance_thresholds至少需要配置一个受支持的门槛")
    return {"passed": all(check["passed"] for check in checks), "checks": checks}


def build_report_payload(
    results: list[IntentEvaluationResult],
    metrics: dict[str, Any],
    metadata: dict[str, Any],
    acceptance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """组合可写入JSON的完整报告，错误样本放在前面便于排查。"""
    failures = [
        asdict(result)
        for result in results
        if not result.intent_correct or (result.expected_slots and not result.slots_exact)
    ]
    return {
        "metadata": metadata,
        "metrics": metrics,
        "acceptance": acceptance,
        "failures": failures,
        "results": [asdict(result) for result in results],
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    """把JSON报告中的核心指标渲染成人工审核友好的Markdown。"""
    metadata = report["metadata"]
    metrics = report["metrics"]
    lines = [
        "# 意图检测评测报告",
        "",
        "本报告只调用语义理解服务，不进入业务编排器，也没有实际调用Tool。",
        "",
        "## 运行信息",
        "",
        f"- 运行时间：{metadata['generated_at']}",
        f"- 模式：{metadata['mode']}",
        f"- 模型：{metadata['model']}",
        f"- 数据集：{metadata['dataset']}",
        f"- 样本数：{metrics['total_cases']}",
        "",
        "## 核心指标",
        "",
        f"- 意图准确率：{_percent(metrics['intent_accuracy'])}",
        f"- 槽位准确率：{_percent(metrics['slot_accuracy'])}（仅统计{metrics['slot_annotated_cases']}条带槽位标注样本）",
        f"- 未知问题召回率：{_percent(metrics['unknown_recall'])}",
        f"- 实际Tool调用次数：{metrics['actual_tool_calls']}",
        f"- 潜在错误Tool路由次数：{metrics['potential_wrong_tool_routes']}",
        f"- LLM降级率：{_percent(metrics['llm_fallback_rate'])}",
        f"- 平均识别耗时：{metrics['average_latency_ms']} ms",
        f"- P50识别耗时：{metrics['p50_latency_ms']} ms",
        f"- P95识别耗时：{metrics['p95_latency_ms']} ms",
    ]

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
            "## 分意图结果",
            "",
            "| 意图 | 正确数 | 总数 | 准确率 |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for intent, values in metrics["per_intent"].items():
        lines.append(
            f"| {intent} | {values['correct']} | {values['total']} | {_percent(values['accuracy'])} |"
        )

    lines.extend(
        [
            "",
            "## 混淆矩阵",
            "",
            "以下格式为“人工标注意图 -> 模型预测意图: 数量”。",
            "",
        ]
    )
    for expected, predictions in metrics["confusion_matrix"].items():
        summary = "，".join(f"{predicted}: {count}" for predicted, count in predictions.items())
        lines.append(f"- {expected} -> {summary}")

    failures = report["failures"]
    lines.extend(["", "## 失败样本", ""])
    if not failures:
        lines.append("没有失败样本。")
    else:
        lines.extend(
            [
                "| ID | 用户说法 | 会话意图 | 期望意图 | 预测意图 | 来源 | 耗时(ms) |",
                "| --- | --- | --- | --- | --- | --- | ---: |",
            ]
        )
        for row in failures:
            safe_text = str(row["text"]).replace("|", "\\|").replace("\n", " ")
            current_intent = row.get("current_intent") or "-"
            lines.append(
                f"| {row['case_id']} | {safe_text} | {current_intent} | "
                f"{row['expected_intent']} | {row['predicted_intent']} | "
                f"{row['source']} | {row['latency_ms']} |"
            )

    return "\n".join(lines) + "\n"

def _ratio(numerator: int, denominator: int) -> float:
    """安全计算0到1之间的比例。"""
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 6)


def _percentile(sorted_values: list[float], percentile: float) -> float:
    """使用nearest-rank计算百分位，适合当前小规模评测集。"""
    if not sorted_values:
        return 0.0
    index = max(0, math.ceil(percentile * len(sorted_values)) - 1)
    return round(sorted_values[index], 2)


def _percent(value: float) -> str:
    """把0到1之间的比例格式化为百分比。"""
    return f"{value * 100:.2f}%"