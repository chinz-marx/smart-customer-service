package com.smartcustomerservice.business.knowledge.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeChunk;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeCodes;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeOutboxEvent;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeQuestion;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeChunkMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeOutboxEventMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeQuestionMapper;
import com.smartcustomerservice.business.knowledge.sync.KnowledgePublishResult;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.List;

/** Outbox状态修改和切片元数据落库都在短事务内执行。 */
@Service
@RequiredArgsConstructor
public class KnowledgeOutboxService {
    private final KnowledgeOutboxEventMapper outboxMapper;
    private final KnowledgeChunkMapper chunkMapper;
    private final KnowledgeQuestionMapper questionMapper;

    @Transactional(readOnly = true)
    public List<KnowledgeOutboxEvent> findReady(int limit) {
        OffsetDateTime staleClaim = OffsetDateTime.now().minusMinutes(5);
        return outboxMapper.selectList(
                Wrappers.<KnowledgeOutboxEvent>lambdaQuery()
                        .and(query -> query
                                .in(KnowledgeOutboxEvent::getStatus,
                                        KnowledgeCodes.OUTBOX_PENDING,
                                        KnowledgeCodes.OUTBOX_FAILED)
                                .le(KnowledgeOutboxEvent::getNextRetryAt, OffsetDateTime.now())
                                .or()
                                .eq(KnowledgeOutboxEvent::getStatus, KnowledgeCodes.OUTBOX_PROCESSING)
                                .lt(KnowledgeOutboxEvent::getProcessedAt, staleClaim))
                        .orderByAsc(KnowledgeOutboxEvent::getId)
                        .last("LIMIT " + Math.min(Math.max(limit, 1), 50)));
    }

    @Transactional
    public boolean claim(KnowledgeOutboxEvent event) {
        int changed = outboxMapper.update(null,
                Wrappers.<KnowledgeOutboxEvent>lambdaUpdate()
                        .set(KnowledgeOutboxEvent::getStatus, KnowledgeCodes.OUTBOX_PROCESSING)
                        .set(KnowledgeOutboxEvent::getProcessedAt, OffsetDateTime.now())
                        .eq(KnowledgeOutboxEvent::getId, event.getId())
                        .eq(KnowledgeOutboxEvent::getStatus, event.getStatus()));
        return changed == 1;
    }

    @Transactional
    public void completePublish(KnowledgeOutboxEvent event, KnowledgePublishResult result) {
        if (result == null || !event.getKnowledgeId().equals(result.knowledgeId())
                || !event.getVersionId().equals(result.versionId())) {
            throw new IllegalStateException("Python返回的知识版本与Outbox事件不一致");
        }

        // 当前版本草稿改为更新，保留chunk_id、问法外键和历史版本数据。
        for (KnowledgePublishResult.ChunkResult item : result.chunks()) {
            KnowledgeChunk chunk = chunkMapper.selectOne(
                    Wrappers.<KnowledgeChunk>lambdaQuery()
                            .eq(KnowledgeChunk::getVersionId, event.getVersionId())
                            .eq(KnowledgeChunk::getChunkNo, item.chunkNo()));
            if (chunk == null) {
                chunk = new KnowledgeChunk();
                chunk.setKnowledgeId(event.getKnowledgeId());
                chunk.setVersionId(event.getVersionId());
                chunk.setChunkNo(item.chunkNo());
                chunk.setChunkContent(item.content());
                chunk.setContentHash(item.contentHash());
                chunk.setIndexVersion(item.indexVersion());
                chunk.setSyncStatus(KnowledgeCodes.CHUNK_SUCCESS);
                chunk.setRedisKey(item.redisKey());
                chunk.setSyncedAt(OffsetDateTime.now());
                chunkMapper.insert(chunk);
            } else {
                chunk.setChunkContent(item.content());
                chunk.setContentHash(item.contentHash());
                chunk.setRedisKey(item.redisKey());
                chunk.setIndexVersion(item.indexVersion());
                chunk.setSyncStatus(KnowledgeCodes.CHUNK_SUCCESS);
                chunk.setSyncError(null);
                chunk.setSyncedAt(OffsetDateTime.now());
                chunkMapper.updateById(chunk);
            }
            saveQuestionResults(event, chunk, item);
        }
        markSuccess(event.getId());
    }

    private void saveQuestionResults(
            KnowledgeOutboxEvent event,
            KnowledgeChunk chunk,
            KnowledgePublishResult.ChunkResult chunkResult) {
        if (chunkResult.questions() == null) {
            return;
        }
        for (KnowledgePublishResult.QuestionResult item : chunkResult.questions()) {
            KnowledgeQuestion question = item.questionId() == null
                    ? questionMapper.selectOne(Wrappers.<KnowledgeQuestion>lambdaQuery()
                            .eq(KnowledgeQuestion::getChunkId, chunk.getId())
                            .eq(KnowledgeQuestion::getQuestionNo, item.questionNo()))
                    : questionMapper.selectById(item.questionId());
            if (question == null) {
                question = new KnowledgeQuestion();
                question.setKnowledgeId(event.getKnowledgeId());
                question.setVersionId(event.getVersionId());
                question.setChunkId(chunk.getId());
                question.setQuestionNo(item.questionNo());
                question.setQuestionText(item.text());
                question.setQuestionHash(item.questionHash());
                question.setSyncStatus(KnowledgeCodes.CHUNK_SUCCESS);
                question.setRedisKey(item.redisKey());
                question.setSyncedAt(OffsetDateTime.now());
                questionMapper.insert(question);
            } else {
                question.setQuestionText(item.text());
                question.setQuestionHash(item.questionHash());
                question.setRedisKey(item.redisKey());
                question.setSyncStatus(KnowledgeCodes.CHUNK_SUCCESS);
                question.setSyncError(null);
                question.setSyncedAt(OffsetDateTime.now());
                questionMapper.updateById(question);
            }
        }
    }

    @Transactional
    public void completeDelete(KnowledgeOutboxEvent event) {
        // 停用只删除Redis在线副本，PostgreSQL保留分片和问法供审计与重新发布。
        markSuccess(event.getId());
    }

    @Transactional
    public void fail(KnowledgeOutboxEvent event, Exception exception) {
        int retry = event.getRetryCount() + 1;
        long delaySeconds = Math.min(300, 1L << Math.min(retry, 8));
        outboxMapper.update(null,
                Wrappers.<KnowledgeOutboxEvent>lambdaUpdate()
                        .set(KnowledgeOutboxEvent::getStatus, KnowledgeCodes.OUTBOX_FAILED)
                        .set(KnowledgeOutboxEvent::getRetryCount, retry)
                        .set(KnowledgeOutboxEvent::getNextRetryAt,
                                OffsetDateTime.now().plusSeconds(delaySeconds))
                        .set(KnowledgeOutboxEvent::getLastError,
                                StringUtils.abbreviate(exception.getMessage(), 1000))
                        .set(KnowledgeOutboxEvent::getProcessedAt, null)
                        .eq(KnowledgeOutboxEvent::getId, event.getId()));
    }

    private void markSuccess(long eventId) {
        outboxMapper.update(null,
                Wrappers.<KnowledgeOutboxEvent>lambdaUpdate()
                        .set(KnowledgeOutboxEvent::getStatus, KnowledgeCodes.OUTBOX_SUCCESS)
                        .set(KnowledgeOutboxEvent::getLastError, null)
                        .set(KnowledgeOutboxEvent::getProcessedAt, OffsetDateTime.now())
                        .eq(KnowledgeOutboxEvent::getId, eventId));
    }
}
