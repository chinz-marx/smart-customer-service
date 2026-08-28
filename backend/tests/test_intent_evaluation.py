from app.evaluation.intent_evaluator import (
    IntentEvaluationResult,
    calculate_metrics,
    evaluate_acceptance_thresholds,
)


def test_calculate_intent_metrics_without_calling_tools() -> None:
    """统计器应正确计算核心指标，并明确实际Tool调用始终为0。"""
    results = [
        IntentEvaluationResult(
            case_id="points-ok",
            text="查询积分，尾号1234",
            expected_intent="points_query",
            predicted_intent="points_query",
            confidence=0.95,
            expected_slots={"phone_tail": "1234"},
            predicted_slots={"phone_tail": "1234"},
            source="llm",
            latency_ms=100,
        ),
        IntentEvaluationResult(
            case_id="reward-wrong",
            text="奖励没到账",
            expected_intent="reward_not_received",
            predicted_intent="points_query",
            confidence=0.78,
            expected_slots={},
            predicted_slots={},
            source="keyword",
            latency_ms=200,
        ),
        IntentEvaluationResult(
            case_id="unknown-wrong",
            text="今天天气怎么样",
            expected_intent="unknown",
            predicted_intent="reward_not_received",
            confidence=0.70,
            expected_slots={},
            predicted_slots={},
            source="llm",
            latency_ms=300,
        ),
        IntentEvaluationResult(
            case_id="handoff-ok",
            text="转人工",
            expected_intent="human_handoff",
            predicted_intent="human_handoff",
            confidence=0.99,
            expected_slots={},
            predicted_slots={},
            source="llm",
            latency_ms=400,
        ),
    ]

    metrics = calculate_metrics(
        results,
        tool_intents={"reward_not_received", "points_query"},
    )

    assert metrics["intent_accuracy"] == 0.5
    assert metrics["slot_accuracy"] == 1.0
    assert metrics["unknown_recall"] == 0.0
    assert metrics["actual_tool_calls"] == 0
    assert metrics["potential_wrong_tool_routes"] == 2
    assert metrics["llm_fallback_rate"] == 0.25
    assert metrics["average_latency_ms"] == 250.0
    assert metrics["p50_latency_ms"] == 200
    assert metrics["p95_latency_ms"] == 400


def test_intent_dataset_has_25_cases_per_category() -> None:
    """每个评测类别必须固定为25条，避免样本数量不同导致指标失真。"""
    from pathlib import Path

    import yaml

    dataset_path = Path(__file__).resolve().parents[1] / "evaluation" / "intent_cases.yaml"
    with dataset_path.open("r", encoding="utf-8") as file:
        payload = yaml.safe_load(file)

    counts: dict[str, int] = {}
    for case in payload["cases"]:
        intent = case["expected_intent"]
        counts[intent] = counts.get(intent, 0) + 1

    assert counts == {
        "activity_rules": 25,
        "benefits_query": 25,
        "complaint": 25,
        "human_handoff": 25,
        "order_query": 25,
        "points_query": 25,
        "refund_request": 25,
        "reward_not_received": 25,
        "unknown": 25,
    }


def test_expanded_intents_are_detection_only() -> None:
    """新增业务意图目前只参与检测评测，不能提前绑定或调用Tool。"""
    from app.configs.loader import load_runtime_config

    detection_only_intents = {
        "activity_rules",
        "benefits_query",
        "complaint",
        "refund_request",
    }
    configs = load_runtime_config().intents

    for intent_name in detection_only_intents:
        intent_config = configs[intent_name]
        assert intent_config.response_strategy == "DETECT_ONLY"
        assert intent_config.tool is None

    order_config = configs["order_query"]
    assert order_config.response_strategy == "TOOL_LLM"
    assert order_config.tool == "order_query"

def test_hard_dataset_has_90_balanced_cases() -> None:
    """难例集必须保持9类均衡，避免总准确率掩盖某个小类表现。"""
    from collections import Counter
    from pathlib import Path

    import yaml

    dataset_path = Path(__file__).resolve().parents[1] / "evaluation" / "intent_hard_cases.yaml"
    with dataset_path.open("r", encoding="utf-8") as file:
        payload = yaml.safe_load(file)

    counts = Counter(case["expected_intent"] for case in payload["cases"])
    assert len(payload["cases"]) == 90
    assert set(counts.values()) == {10}
    assert sum(bool(case.get("current_intent")) for case in payload["cases"]) == 9


def test_acceptance_thresholds_explain_failed_metric() -> None:
    """任一生产门槛未达标时，结果必须失败并指出具体指标。"""
    metrics = {
        "intent_accuracy": 0.94,
        "unknown_recall": 1.0,
        "potential_wrong_tool_routes": 0,
        "llm_fallback_rate": 0.01,
        "llm_error_count": 0,
        "average_latency_ms": 2100.0,
        "per_intent": {
            "order_query": {"accuracy": 0.90},
            "unknown": {"accuracy": 1.0},
        },
    }
    acceptance = evaluate_acceptance_thresholds(
        metrics,
        {
            "min_intent_accuracy": 0.95,
            "min_per_intent_accuracy": 0.90,
            "max_average_latency_ms": 3000,
        },
    )

    assert acceptance["passed"] is False
    failed = [check["name"] for check in acceptance["checks"] if not check["passed"]]
    assert failed == ["min_intent_accuracy"]

def test_cache_regression_dataset_is_balanced() -> None:
    """双检索接入后的独立回归集应保持9类均衡，只标注意图不标注槽位。"""
    from collections import Counter
    from pathlib import Path

    import yaml

    path = Path(__file__).resolve().parents[1] / "evaluation" / "intent_cache_regression.yaml"
    with path.open("r", encoding="utf-8") as file:
        payload = yaml.safe_load(file)

    cases = payload["cases"]
    counts = Counter(case["expected_intent"] for case in cases)
    assert len(cases) == 45
    assert len(counts) == 9
    assert set(counts.values()) == {5}
    assert all(not case.get("expected_slots") for case in cases)
