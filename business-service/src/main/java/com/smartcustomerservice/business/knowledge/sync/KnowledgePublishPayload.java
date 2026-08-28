package com.smartcustomerservice.business.knowledge.sync;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.OffsetDateTime;
import java.util.List;

/** Java审批版本发送给Python索引发布器的不可变请求。 */
public record KnowledgePublishPayload(
        @JsonProperty("knowledge_id") Long knowledgeId,
        @JsonProperty("knowledge_code") String knowledgeCode,
        @JsonProperty("version_id") Long versionId,
        @JsonProperty("version_no") Integer versionNo,
        String title,
        String content,
        String category,
        List<String> tags,
        String intent,
        @JsonProperty("effective_at") String effectiveAt,
        @JsonProperty("expired_at") String expiredAt,
        List<ChunkPayload> chunks) {

    /** 传输层统一使用ISO-8601字符串，不依赖Jackson额外的Java Time模块。 */
    public KnowledgePublishPayload(
            Long knowledgeId,
            String knowledgeCode,
            Long versionId,
            Integer versionNo,
            String title,
            String content,
            String category,
            List<String> tags,
            String intent,
            OffsetDateTime effectiveAt,
            OffsetDateTime expiredAt,
            List<ChunkPayload> chunks) {
        this(
                knowledgeId,
                knowledgeCode,
                versionId,
                versionNo,
                title,
                content,
                category,
                tags,
                intent,
                effectiveAt.toString(),
                expiredAt == null ? null : expiredAt.toString(),
                chunks);
    }

    /** 一个已审核原子分片及其标准问法。 */
    public record ChunkPayload(
            @JsonProperty("chunk_no") Integer chunkNo,
            String content,
            List<QuestionPayload> questions) {
    }

    /** 标准问法使用数据库主键作为Redis精确映射的稳定身份。 */
    public record QuestionPayload(
            @JsonProperty("question_id") Long questionId,
            @JsonProperty("question_no") Integer questionNo,
            String text) {
    }
}
