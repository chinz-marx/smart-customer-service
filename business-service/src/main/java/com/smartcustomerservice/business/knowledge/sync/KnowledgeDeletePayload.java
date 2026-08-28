package com.smartcustomerservice.business.knowledge.sync;

import com.fasterxml.jackson.annotation.JsonProperty;

/** 停用审批通过后发送给Python的删除请求。 */
public record KnowledgeDeletePayload(
        @JsonProperty("knowledge_id") Long knowledgeId,
        @JsonProperty("knowledge_code") String knowledgeCode) {
}
