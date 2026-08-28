from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


# scripts目录不属于Python包，显式加入backend根目录以兼容Windows和Linux直接执行。
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import Settings
from app.configs.loader import load_runtime_config
from app.evaluation.intent_evaluator import (
    IntentEvaluationCase,
    build_report_payload,
    calculate_metrics,
    evaluate_acceptance_thresholds,
    evaluate_intents,
    render_markdown_report,
)
from app.schemas import ChatHistoryItem
from app.understanding.service import UnderstandingService


DEFAULT_DATASET = BACKEND_DIR / "evaluation" / "intent_cases.yaml"
DEFAULT_REPORT_DIR = BACKEND_DIR / "evaluation" / "reports"


def parse_args() -> argparse.Namespace:
    """定义Windows和Linux都能使用的命令行参数。"""
    parser = argparse.ArgumentParser(description="运行智能客服意图检测评测")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--mode", choices=("hybrid", "llm", "keyword"), default="hybrid")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="只运行前N条；0表示运行全部数据。",
    )
    parser.add_argument(
        "--check-thresholds",
        action="store_true",
        help="按照数据集中的acceptance_thresholds验收，未通过时返回退出码2。",
    )
    return parser.parse_args()


def load_cases(path: Path) -> tuple[dict[str, Any], list[IntentEvaluationCase]]:
    """使用PyYAML安全读取人工标注数据集。

    难例可以携带最近对话和当前会话状态，用于测试“还是转人工”等依赖上下文的表达。
    """
    with path.resolve().open("r", encoding="utf-8") as file:
        payload = yaml.safe_load(file) or {}
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise ValueError("数据集必须包含cases列表")

    cases: list[IntentEvaluationCase] = []
    seen_ids: set[str] = set()
    for raw_case in payload["cases"]:
        if not isinstance(raw_case, dict):
            raise ValueError("每条评测样本必须是字典")
        case = IntentEvaluationCase(
            case_id=str(raw_case["id"]),
            text=str(raw_case["text"]),
            expected_intent=str(raw_case["expected_intent"]),
            expected_slots={
                str(code): str(value)
                for code, value in (raw_case.get("expected_slots") or {}).items()
            },
            history=tuple(
                ChatHistoryItem.model_validate(item)
                for item in (raw_case.get("history") or [])
            ),
            current_intent=(
                str(raw_case["current_intent"])
                if raw_case.get("current_intent")
                else None
            ),
            current_slots={
                str(code): str(value)
                for code, value in (raw_case.get("current_slots") or {}).items()
            },
        )
        if case.case_id in seen_ids:
            raise ValueError(f"样本ID重复：{case.case_id}")
        seen_ids.add(case.case_id)
        cases.append(case)

    return payload, cases


async def run(
    args: argparse.Namespace,
) -> tuple[Path, Path, dict[str, Any], dict[str, Any] | None]:
    """执行评测并同时写出JSON明细和Markdown摘要。"""
    dataset_path = args.dataset.resolve()
    dataset, cases = load_cases(dataset_path)
    if args.limit > 0:
        cases = cases[: args.limit]
    if not cases:
        raise ValueError("没有可运行的评测样本")

    settings = Settings(understanding_mode=args.mode)
    if args.mode != "keyword" and not settings.has_real_understanding_api_key:
        raise RuntimeError("请先在backend/.env配置UNDERSTANDING_API_KEY")

    configured_intents = set(load_runtime_config().intents)
    allowed_intents = configured_intents | {"unknown"}
    referenced_intents = {case.expected_intent for case in cases}
    referenced_intents.update(
        case.current_intent for case in cases if case.current_intent
    )
    invalid_intents = sorted(referenced_intents - allowed_intents)
    if invalid_intents:
        raise ValueError(f"数据集包含未配置意图：{invalid_intents}")

    service = UnderstandingService(settings)
    results = await evaluate_intents(cases, service, concurrency=args.concurrency)

    runtime_config = load_runtime_config()
    tool_intents = {
        intent.code
        for intent in runtime_config.intents.values()
        if intent.tool and intent.response_strategy == "TOOL_LLM"
    }
    metrics = calculate_metrics(results, tool_intents)

    raw_thresholds = dataset.get("acceptance_thresholds")
    acceptance = None
    if raw_thresholds is not None:
        if not isinstance(raw_thresholds, dict):
            raise ValueError("acceptance_thresholds必须是字典")
        acceptance = evaluate_acceptance_thresholds(metrics, raw_thresholds)

    generated_at = datetime.now(timezone.utc)
    report = build_report_payload(
        results=results,
        metrics=metrics,
        metadata={
            "generated_at": generated_at.isoformat(),
            "mode": args.mode,
            "model": (
                "keyword"
                if args.mode == "keyword"
                else settings.effective_understanding_model
            ),
            "base_url": (
                None if args.mode == "keyword" else settings.understanding_base_url
            ),
            "dataset": str(dataset_path.relative_to(BACKEND_DIR)),
            "dataset_version": dataset.get("version", 1),
            "concurrency": args.concurrency,
            "tool_execution_enabled": False,
        },
        acceptance=acceptance,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = generated_at.strftime("%Y%m%d-%H%M%S")
    json_path = args.output_dir / f"intent-evaluation-{stamp}.json"
    markdown_path = args.output_dir / f"intent-evaluation-{stamp}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown_report(report), encoding="utf-8")
    return json_path, markdown_path, metrics, acceptance


def print_summary(
    json_path: Path,
    markdown_path: Path,
    metrics: dict[str, Any],
    acceptance: dict[str, Any] | None,
) -> None:
    """在终端输出最重要的指标、验收结论和报告相对路径。"""
    print(f"样本数: {metrics['total_cases']}")
    print(f"意图准确率: {metrics['intent_accuracy'] * 100:.2f}%")
    print(f"槽位准确率: {metrics['slot_accuracy'] * 100:.2f}%")
    print(f"未知问题召回率: {metrics['unknown_recall'] * 100:.2f}%")
    print(f"实际Tool调用次数: {metrics['actual_tool_calls']}")
    print(f"潜在错误Tool路由次数: {metrics['potential_wrong_tool_routes']}")
    print(f"LLM降级率: {metrics['llm_fallback_rate'] * 100:.2f}%")
    print(f"平均识别耗时: {metrics['average_latency_ms']} ms")
    if acceptance:
        print(f"自动验收: {'通过' if acceptance['passed'] else '未通过'}")
    print(f"JSON报告: {json_path.relative_to(BACKEND_DIR)}")
    print(f"Markdown报告: {markdown_path.relative_to(BACKEND_DIR)}")


def main() -> None:
    """命令行主入口；启用门槛检查时，未通过会返回退出码2。"""
    args = parse_args()
    json_path, markdown_path, metrics, acceptance = asyncio.run(run(args))
    print_summary(json_path, markdown_path, metrics, acceptance)
    if args.check_thresholds and acceptance and not acceptance["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()