package com.smartcustomerservice.business.learning.api.dto;

import java.time.OffsetDateTime;

/** 一个问题簇中的真实用户样本，供审核员和LLM交叉检查。 */
public record ProblemSampleItem(
        long id,
        String rootQuestion,
        String originalAnswer,
        int sourceType,
        Double confidence,
        String conversationId,
        OffsetDateTime occurredAt) {
}
