package com.smartcustomerservice.business.learning.api.dto;

import java.time.OffsetDateTime;

/** 标准回答生成和人工审核的历史记录。 */
public record ProblemReviewItem(
        long id,
        int actionType,
        int statusBefore,
        int statusAfter,
        String answerSnapshot,
        String comment,
        String operatorId,
        OffsetDateTime createdAt,
        OffsetDateTime processedAt) {
}
