from app.config import Settings
from app.evaluation.release_gate import ReleaseCaseResult, calculate_release_acceptance


def case(case_id: int, at1: bool, at3: bool, threshold: bool) -> ReleaseCaseResult:
    return ReleaseCaseResult(
        case_id=case_id,
        question=f"问题{case_id}",
        passed_at_1=at1,
        passed_at_3=at3,
        passed_threshold=threshold,
        top_knowledge_id=10,
        top_version_id=20,
        top_chunk_no=0,
        top_distance=0.2,
        latency_ms=10.0,
    )


def negative_case(case_id: int, correctly_rejected: bool) -> ReleaseCaseResult:
    return ReleaseCaseResult(
        case_id=case_id,
        question=f"困难负样本{case_id}",
        expected_match=False,
        passed_at_1=correctly_rejected,
        passed_at_3=correctly_rejected,
        passed_threshold=correctly_rejected,
        top_knowledge_id=None,
        top_version_id=None,
        top_chunk_no=None,
        top_distance=None,
        latency_ms=10.0,
    )


def test_release_gate_passes_when_all_thresholds_are_met() -> None:
    settings = Settings(
        release_min_recall_at_1=0.8,
        release_min_recall_at_3=1.0,
        release_min_threshold_recall=0.8,
    )
    results = [case(index, index != 5, True, index != 5) for index in range(1, 6)]

    report = calculate_release_acceptance(100, results, settings)

    assert report.passed is True
    assert report.recall_at_1 == 0.8
    assert report.recall_at_3 == 1.0


def test_release_gate_fails_when_threshold_recall_is_low() -> None:
    settings = Settings(release_min_threshold_recall=0.8)
    results = [case(index, True, True, index <= 3) for index in range(1, 6)]

    report = calculate_release_acceptance(101, results, settings)

    assert report.passed is False
    assert report.threshold_recall == 0.6


def test_release_gate_fails_when_hard_negative_hits_candidate() -> None:
    settings = Settings(release_max_hard_negative_false_positive_rate=0.0)
    results = [case(index, True, True, True) for index in range(1, 6)]
    results.extend([negative_case(6, True), negative_case(7, False)])

    report = calculate_release_acceptance(102, results, settings)

    assert report.passed is False
    assert report.hard_negative_cases == 2
    assert report.hard_negative_false_positive_rate == 0.5
