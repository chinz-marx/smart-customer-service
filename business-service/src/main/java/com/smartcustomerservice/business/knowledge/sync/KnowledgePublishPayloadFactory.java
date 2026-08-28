package com.smartcustomerservice.business.knowledge.sync;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.smartcustomerservice.business.knowledge.domain.Knowledge;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeCategory;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeChunk;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeQuestion;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeVersion;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeCategoryMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeChunkMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeQuestionMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.Arrays;
import java.util.List;

/** 统一构建发布与自动验收使用的知识快照，避免两条链路读取出不同内容。 */
@Component
@RequiredArgsConstructor
public class KnowledgePublishPayloadFactory {
    private final KnowledgeCategoryMapper categoryMapper;
    private final KnowledgeChunkMapper chunkMapper;
    private final KnowledgeQuestionMapper questionMapper;

    public KnowledgePublishPayload build(Knowledge knowledge, KnowledgeVersion version) {
        KnowledgeCategory category = required(
                categoryMapper.selectById(knowledge.getCategoryId()), "知识分类");
        return new KnowledgePublishPayload(
                knowledge.getId(), knowledge.getKnowledgeCode(),
                version.getId(), version.getVersionNo(), version.getTitle(), version.getContent(),
                category.getCategoryName(), Arrays.asList(version.getTags()),
                version.getIntentCode(), version.getEffectiveAt(), version.getExpiredAt(),
                loadChunks(version.getId()));
    }

    private List<KnowledgePublishPayload.ChunkPayload> loadChunks(Long versionId) {
        return chunkMapper.selectList(Wrappers.<KnowledgeChunk>lambdaQuery()
                        .eq(KnowledgeChunk::getVersionId, versionId)
                        .orderByAsc(KnowledgeChunk::getChunkNo))
                .stream()
                .map(chunk -> new KnowledgePublishPayload.ChunkPayload(
                        chunk.getChunkNo(),
                        chunk.getChunkContent(),
                        questionMapper.selectList(Wrappers.<KnowledgeQuestion>lambdaQuery()
                                        .eq(KnowledgeQuestion::getChunkId, chunk.getId())
                                        .orderByAsc(KnowledgeQuestion::getQuestionNo))
                                .stream()
                                .map(question -> new KnowledgePublishPayload.QuestionPayload(
                                        question.getId(),
                                        question.getQuestionNo(),
                                        question.getQuestionText()))
                                .toList()))
                .toList();
    }

    private <T> T required(T value, String name) {
        if (value == null) {
            throw new IllegalStateException(name + "不存在，无法构建知识快照");
        }
        return value;
    }
}
