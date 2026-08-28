package com.smartcustomerservice.business.knowledge.api.dto;

import java.time.OffsetDateTime;

/** FAQ流式回答完成事件；不重复携带问题和完整答案。 */
public record CustomerFaqStreamDone(
        Long questionId,
        String source,
        String sessionId,
        String conversationId,
        String userMessageId,
        String assistantMessageId,
        OffsetDateTime createdAt) {
}
