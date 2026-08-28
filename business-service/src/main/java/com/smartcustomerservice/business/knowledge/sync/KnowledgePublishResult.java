package com.smartcustomerservice.business.knowledge.sync;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/** Python发布成功后返回的分片和标准问法索引清单。 */
public record KnowledgePublishResult(
        @JsonProperty("knowledge_id") Long knowledgeId,
        @JsonProperty("version_id") Long versionId,
        List<ChunkResult> chunks) {

    public record ChunkResult(
            @JsonProperty("chunk_no") Integer chunkNo,
            String content,
            @JsonProperty("content_hash") String contentHash,
            @JsonProperty("redis_key") String redisKey,
            @JsonProperty("index_version") Integer indexVersion,
            List<QuestionResult> questions) {
    }

    public record QuestionResult(
            @JsonProperty("question_id") Long questionId,
            @JsonProperty("question_no") Integer questionNo,
            String text,
            @JsonProperty("question_hash") String questionHash,
            @JsonProperty("redis_key") String redisKey) {
    }
}
