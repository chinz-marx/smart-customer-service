package com.smartcustomerservice.business.learning.api.dto;

/** 评测中心展示的一条自动发布验收用例结果。 */
public record EvaluationRunCaseResultItem(
        long caseId,
        String caseCode,
        String questionText,
        String caseCategory,
        int difficulty,
        boolean expectedMatch,
        boolean passedAt1,
        boolean passedAt3,
        boolean passedThreshold,
        Double topDistance,
        Double latencyMs,
        String errorMessage) {
}
