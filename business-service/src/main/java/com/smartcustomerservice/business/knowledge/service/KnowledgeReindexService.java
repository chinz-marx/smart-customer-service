package com.smartcustomerservice.business.knowledge.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartcustomerservice.business.knowledge.api.dto.KnowledgeReindexResult;
import com.smartcustomerservice.business.knowledge.domain.Knowledge;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeCodes;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeOutboxEvent;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeVersion;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeOutboxEventMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeVersionMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 为当前已发布知识重新投递索引事件。
 *
 * <p>这里不直接操作Redis，也不改变审批结果。Java只确定数据库中的线上版本并写入Outbox，
 * 后续仍由现有Worker调用Python完成切片、Embedding和Redis Search发布。</p>
 */
@Service
@RequiredArgsConstructor
public class KnowledgeReindexService {
    private final KnowledgeMapper knowledgeMapper;
    private final KnowledgeVersionMapper versionMapper;
    private final KnowledgeOutboxEventMapper outboxMapper;
    private final ObjectMapper objectMapper;

    @Transactional
    public KnowledgeReindexResult reindexPublished(String operatorId) {
        List<Knowledge> activeKnowledge = knowledgeMapper.selectList(
                Wrappers.<Knowledge>lambdaQuery()
                        .eq(Knowledge::getStatus, KnowledgeCodes.KNOWLEDGE_ACTIVE)
                        .isNotNull(Knowledge::getCurrentVersionId)
                        .orderByAsc(Knowledge::getId));

        int queued = 0;
        int reset = 0;
        int skipped = 0;
        OffsetDateTime now = OffsetDateTime.now();
        for (Knowledge knowledge : activeKnowledge) {
            KnowledgeVersion version = versionMapper.selectById(knowledge.getCurrentVersionId());
            if (!isPublishableCurrentVersion(knowledge, version, now)) {
                skipped++;
                continue;
            }

            KnowledgeOutboxEvent unfinished = findUnfinishedEvent(knowledge.getId(), version.getId());
            if (unfinished != null) {
                // 复用未完成事件，避免管理员重复点击时制造多份相同任务。
                unfinished.setStatus(KnowledgeCodes.OUTBOX_PENDING);
                unfinished.setRetryCount(0);
                unfinished.setNextRetryAt(now);
                unfinished.setLastError(null);
                unfinished.setProcessedAt(null);
                unfinished.setPayload(payload(operatorId, "manual-reindex-reset"));
                outboxMapper.updateById(unfinished);
                reset++;
                continue;
            }

            KnowledgeOutboxEvent event = new KnowledgeOutboxEvent();
            event.setEventId(UUID.randomUUID().toString());
            event.setKnowledgeId(knowledge.getId());
            event.setVersionId(version.getId());
            event.setEventType(KnowledgeCodes.EVENT_UPSERT);
            event.setPayload(payload(operatorId, "manual-reindex"));
            event.setStatus(KnowledgeCodes.OUTBOX_PENDING);
            event.setRetryCount(0);
            event.setNextRetryAt(now);
            outboxMapper.insert(event);
            queued++;
        }
        return new KnowledgeReindexResult(queued, reset, skipped);
    }

    private boolean isPublishableCurrentVersion(
            Knowledge knowledge, KnowledgeVersion version, OffsetDateTime now) {
        return version != null
                && knowledge.getId().equals(version.getKnowledgeId())
                && Integer.valueOf(KnowledgeCodes.VERSION_PUBLISHED).equals(version.getVersionStatus())
                && version.getEffectiveAt() != null
                && !version.getEffectiveAt().isAfter(now)
                && (version.getExpiredAt() == null || version.getExpiredAt().isAfter(now));
    }

    private KnowledgeOutboxEvent findUnfinishedEvent(Long knowledgeId, Long versionId) {
        return outboxMapper.selectLatestUnfinishedUpsert(knowledgeId, versionId);
    }

    private String payload(String operatorId, String source) {
        try {
            // 使用Jackson生成JSON，避免操作人ID包含特殊字符时产生无效Outbox载荷。
            return objectMapper.writeValueAsString(Map.of(
                    "source", source,
                    "operatorId", operatorId));
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("重建索引事件序列化失败", exception);
        }
    }
}
