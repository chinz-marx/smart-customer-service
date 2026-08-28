package com.smartcustomerservice.business.learning.api.dto;

import java.time.OffsetDateTime;

/** 评测中心展示的一次自动发布验收摘要。 */
public record EvaluationRunListItem(
        long id,
        String runNo,
        String problemCode,
        String knowledgeCode,
        String knowledgeTitle,
        long versionId,
        int versionNo,
        int status,
        int retryCount,
        int totalCases,
        Double recallAt1,
        Double recallAt3,
        Double thresholdRecall,
        int positiveCases,
        int hardNegativeCases,
        Double hardNegativeFalsePositiveRate,
        Integer errorCount,
        Double averageLatencyMs,
        Double p95LatencyMs,
        Double distanceThreshold,
        String errorMessage,
        OffsetDateTime startedAt,
        OffsetDateTime finishedAt,
        OffsetDateTime createdAt) {
}
