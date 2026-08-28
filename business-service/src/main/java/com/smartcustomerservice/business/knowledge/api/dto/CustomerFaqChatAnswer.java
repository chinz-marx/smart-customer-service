package com.smartcustomerservice.business.knowledge.api.dto;

import java.time.OffsetDateTime;

/** FAQ确定性回答及持久化后的聊天身份。 */
public record CustomerFaqChatAnswer(
        Long questionId,
        String questionText,
        String answer,
        String source,
        String sessionId,
        String conversationId,
        String userMessageId,
        String assistantMessageId,
        OffsetDateTime createdAt) {
}
