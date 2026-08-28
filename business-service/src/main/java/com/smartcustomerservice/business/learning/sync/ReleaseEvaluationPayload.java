package com.smartcustomerservice.business.learning.sync;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.smartcustomerservice.business.knowledge.sync.KnowledgePublishPayload;

import java.util.List;

/** Java 发送给 Python 正式评测执行器的请求。 */
public record ReleaseEvaluationPayload(
        @JsonProperty("run_id") long runId,
        KnowledgePublishPayload knowledge,
        List<CasePayload> cases) {

    /** 单条验收用例只传检索所需的信息，预期答案仍保存在 PostgreSQL。 */
    public record CasePayload(
            @JsonProperty("case_id") long caseId,
            String question,
            @JsonProperty("expected_intent") String expectedIntent,
            @JsonProperty("expected_match") boolean expectedMatch) {
    }
}
