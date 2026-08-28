package com.smartcustomerservice.business.learning.sync;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/** Python 正式评测执行器返回的门槛指标和逐用例结果。 */
public record ReleaseEvaluationResult(
        @JsonProperty("run_id") long runId,
        boolean passed,
        @JsonProperty("total_cases") int totalCases,
        @JsonProperty("recall_at_1") double recallAt1,
        @JsonProperty("recall_at_3") double recallAt3,
        @JsonProperty("threshold_recall") double thresholdRecall,
        @JsonProperty("positive_cases") int positiveCases,
        @JsonProperty("hard_negative_cases") int hardNegativeCases,
        @JsonProperty("hard_negative_false_positive_rate") double hardNegativeFalsePositiveRate,
        @JsonProperty("error_count") int errorCount,
        @JsonProperty("average_latency_ms") double averageLatencyMs,
        @JsonProperty("p95_latency_ms") double p95LatencyMs,
        @JsonProperty("distance_threshold") double distanceThreshold,
        List<CaseResult> cases) {

    public record CaseResult(
            @JsonProperty("case_id") long caseId,
            String question,
            @JsonProperty("expected_match") boolean expectedMatch,
            @JsonProperty("passed_at_1") boolean passedAt1,
            @JsonProperty("passed_at_3") boolean passedAt3,
            @JsonProperty("passed_threshold") boolean passedThreshold,
            @JsonProperty("top_knowledge_id") Long topKnowledgeId,
            @JsonProperty("top_version_id") Long topVersionId,
            @JsonProperty("top_chunk_no") Integer topChunkNo,
            @JsonProperty("top_distance") Double topDistance,
            @JsonProperty("latency_ms") double latencyMs,
            @JsonProperty("error_message") String errorMessage) {
    }
}
