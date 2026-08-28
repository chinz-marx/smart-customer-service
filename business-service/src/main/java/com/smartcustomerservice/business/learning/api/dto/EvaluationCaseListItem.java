package com.smartcustomerservice.business.learning.api.dto;

import java.time.OffsetDateTime;

/** 评测中心展示的一条问题学习回归用例。 */
public record EvaluationCaseListItem(
        long id,
        String caseCode,
        String problemCode,
        String knowledgeCode,
        String knowledgeTitle,
        long versionId,
        int versionNo,
        String questionText,
        String expectedAnswer,
        String expectedIntent,
        int caseType,
        String caseCategory,
        int difficulty,
        int sourceType,
        boolean expectedMatch,
        int status,
        String generatedModel,
        String createdBy,
        String approvedBy,
        OffsetDateTime createdAt,
        OffsetDateTime approvedAt) {
}
