from app.evaluation.knowledge_retrieval_evaluator import (
    KnowledgeRetrievalResult,
    RetrievalCandidate,
    build_retrieval_report,
    calculate_retrieval_metrics,
    evaluate_retrieval_acceptance,
    render_retrieval_markdown,
)


def candidate(
    knowledge_id: int, chunk_no: int, distance: float
) -> RetrievalCandidate:
    """构造稳定的候选数据，单元测试不连接真实Redis和Embedding模型。"""
    return RetrievalCandidate(
        source_id=f"{knowledge_id}:101:{chunk_no}",
        knowledge_id=knowledge_id,
        version_id=101,
        chunk_no=chunk_no,
        distance=distance,
    )


def build_results() -> list[KnowledgeRetrievalResult]:
    """覆盖Top1错误、Top3正确、负样本拒绝和阈值误命中四种情况。"""
    return [
        KnowledgeRetrievalResult(
            case_id="positive-1",
            text="正样本一",
            expected_match=True,
            expected_chunk_no=0,
            candidates=(candidate(29, 0, 0.40), candidate(10, 0, 0.50)),
            latency_ms=100.0,
        ),
        KnowledgeRetrievalResult(
            case_id="positive-2",
            text="正样本二",
            expected_match=True,
            expected_chunk_no=2,
            candidates=(candidate(10, 0, 0.35), candidate(29, 2, 0.42)),
            latency_ms=200.0,
        ),
        KnowledgeRetrievalResult(
            case_id="negative-1",
            text="负样本一",
            expected_match=False,
            expected_chunk_no=None,
            candidates=(candidate(10, 0, 0.45),),
            latency_ms=300.0,
        ),
        KnowledgeRetrievalResult(
            case_id="negative-2",
            text="负样本二",
            expected_match=False,
            expected_chunk_no=None,
            candidates=(candidate(11, 0, 0.60),),
            latency_ms=400.0,
        ),
    ]


def test_metrics_distinguish_candidate_recall_from_threshold_recall() -> None:
    metrics = calculate_retrieval_metrics(
        results=build_results(),
        target_knowledge_id=29,
        configured_threshold=0.38,
        threshold_candidates=[0.38, 0.42, 0.46],
        max_negative_false_positive_rate=0.10,
    )

    assert metrics["knowledge_recall_at_1"] == 0.5
    assert metrics["knowledge_recall_at_3"] == 1.0
    assert metrics["chunk_recall_at_1"] == 0.5
    assert metrics["chunk_recall_at_3"] == 1.0
    assert metrics["configured_threshold_result"]["positive_recall"] == 0.0
    assert metrics["configured_threshold_result"]["negative_false_positive_rate"] == 0.0
    assert metrics["recommended_threshold"]["threshold"] == 0.42


def test_acceptance_and_markdown_report_preserve_failed_gate() -> None:
    results = build_results()
    metrics = calculate_retrieval_metrics(
        results=results,
        target_knowledge_id=29,
        configured_threshold=0.38,
        threshold_candidates=[0.38, 0.42, 0.46],
        max_negative_false_positive_rate=0.10,
    )
    acceptance = evaluate_retrieval_acceptance(
        metrics,
        {
            "min_knowledge_recall_at_3": 0.90,
            "min_chunk_recall_at_3": 0.75,
            "min_configured_positive_recall": 0.80,
            "max_configured_negative_false_positive_rate": 0.10,
            "max_error_count": 0,
        },
    )
    report = build_retrieval_report(
        results=results,
        metrics=metrics,
        metadata={
            "generated_at": "2026-08-07T00:00:00+00:00",
            "dataset": "evaluation/knowledge_retrieval_cases.yaml",
            "target_title": "周年庆全渠道优惠与售后处理规则",
            "target_knowledge_id": 29,
            "embedding_model": "test-embedding",
        },
        acceptance=acceptance,
    )
    markdown = render_retrieval_markdown(report)

    assert acceptance["passed"] is False
    assert "# 知识向量召回评测报告" in markdown
    assert "自动验收" in markdown
    assert "未通过" in markdown
