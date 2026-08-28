package com.smartcustomerservice.business.knowledge.api.dto;

/** 不经过模型、由Redis或PostgreSQL确定性返回的标准问法答案。 */
public record CustomerFaqAnswer(
        Long questionId,
        String questionText,
        String answer,
        String source) {
}
