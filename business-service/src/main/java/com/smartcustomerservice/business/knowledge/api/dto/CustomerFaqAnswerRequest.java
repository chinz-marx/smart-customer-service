package com.smartcustomerservice.business.knowledge.api.dto;

import jakarta.validation.constraints.Size;

/** FAQ直达回答沿用当前会话；两个ID都为空时由Java创建新会话。 */
public record CustomerFaqAnswerRequest(
        @Size(max = 64) String sessionId,
        @Size(max = 36) String conversationId) {
}
