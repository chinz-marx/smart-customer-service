package com.smartcustomerservice.business.knowledge.sync;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.smartcustomerservice.business.knowledge.domain.Knowledge;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeChunk;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeQuestion;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeCategory;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeCodes;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeOutboxEvent;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeVersion;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeCategoryMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeChunkMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeQuestionMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeVersionMapper;
import com.smartcustomerservice.business.knowledge.service.KnowledgeOutboxService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.Arrays;
import java.util.List;

/** 周期消费Outbox；Python或Redis短暂不可用时自动退避重试。 */
@Slf4j
@Component
@RequiredArgsConstructor
public class KnowledgeOutboxWorker {
    private final KnowledgeOutboxService outboxService;
    private final KnowledgeMapper knowledgeMapper;
    private final KnowledgeVersionMapper versionMapper;
    private final KnowledgeCategoryMapper categoryMapper;
    private final KnowledgeChunkMapper chunkMapper;
    private final KnowledgeQuestionMapper questionMapper;
    private final PythonKnowledgeSyncClient syncClient;

    @Scheduled(
            fixedDelayString = "${knowledge.sync.interval-ms:5000}",
            initialDelayString = "${knowledge.sync.initial-delay-ms:3000}")
    public void publishReadyEvents() {
        for (KnowledgeOutboxEvent event : outboxService.findReady(10)) {
            if (!outboxService.claim(event)) {
                continue;
            }
            try {
                process(event);
            } catch (Exception exception) {
                log.warn("知识索引同步失败: eventId={}, retry={}",
                        event.getEventId(), event.getRetryCount() + 1, exception);
                outboxService.fail(event, exception);
            }
        }
    }

    private void process(KnowledgeOutboxEvent event) {
        Knowledge knowledge = required(knowledgeMapper.selectById(event.getKnowledgeId()), "知识");
        KnowledgeVersion version = required(versionMapper.selectById(event.getVersionId()), "知识版本");
        if (event.getEventType() == KnowledgeCodes.EVENT_DELETE) {
            syncClient.delete(new KnowledgeDeletePayload(
                    knowledge.getId(), knowledge.getKnowledgeCode()));
            outboxService.completeDelete(event);
            return;
        }

        KnowledgeCategory category = required(
                categoryMapper.selectById(knowledge.getCategoryId()), "知识分类");
        KnowledgePublishPayload payload = new KnowledgePublishPayload(
                knowledge.getId(), knowledge.getKnowledgeCode(),
                version.getId(), version.getVersionNo(), version.getTitle(), version.getContent(),
                category.getCategoryName(), Arrays.asList(version.getTags()),
                version.getIntentCode(), version.getEffectiveAt(), version.getExpiredAt(),
                loadChunks(version.getId()));
        KnowledgePublishResult result = syncClient.publish(payload);
        outboxService.completePublish(event, result);
    }

    /** 读取审批版本已经保存的原子分片和标准问法。 */
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
            throw new IllegalStateException(name + "不存在，无法同步Redis索引");
        }
        return value;
    }
}
