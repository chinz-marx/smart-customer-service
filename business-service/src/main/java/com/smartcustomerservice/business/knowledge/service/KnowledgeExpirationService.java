package com.smartcustomerservice.business.knowledge.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.smartcustomerservice.business.knowledge.domain.Knowledge;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeCodes;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeOutboxEvent;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeVersion;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeOutboxEventMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeVersionMapper;
import com.smartcustomerservice.business.knowledge.sync.ExpiredKnowledgeItem;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.UUID;

/** 到达expired_at后自动停用知识，并通过Outbox可靠删除Redis索引。 */
@Service
@RequiredArgsConstructor
public class KnowledgeExpirationService {
    private static final String SYSTEM_OPERATOR = "system-expiration";

    private final KnowledgeMapper knowledgeMapper;
    private final KnowledgeVersionMapper versionMapper;
    private final KnowledgeOutboxEventMapper outboxMapper;
    private final KnowledgeAuditService auditService;

    @Transactional
    public void expire(ExpiredKnowledgeItem item) {
        // 条件更新是多实例竞争保护：只有第一个把ACTIVE改为INACTIVE的实例继续处理。
        int changed = knowledgeMapper.update(null,
                Wrappers.<Knowledge>lambdaUpdate()
                        .set(Knowledge::getStatus, KnowledgeCodes.KNOWLEDGE_INACTIVE)
                        .set(Knowledge::getUpdatedBy, SYSTEM_OPERATOR)
                        .eq(Knowledge::getId, item.getKnowledgeId())
                        .eq(Knowledge::getCurrentVersionId, item.getVersionId())
                        .eq(Knowledge::getStatus, KnowledgeCodes.KNOWLEDGE_ACTIVE));
        if (changed == 0) {
            return;
        }

        versionMapper.update(null,
                Wrappers.<KnowledgeVersion>lambdaUpdate()
                        .set(KnowledgeVersion::getVersionStatus, KnowledgeCodes.VERSION_ARCHIVED)
                        .set(KnowledgeVersion::getUpdatedBy, SYSTEM_OPERATOR)
                        .eq(KnowledgeVersion::getId, item.getVersionId()));

        KnowledgeOutboxEvent event = new KnowledgeOutboxEvent();
        event.setEventId(UUID.randomUUID().toString());
        event.setKnowledgeId(item.getKnowledgeId());
        event.setVersionId(item.getVersionId());
        event.setEventType(KnowledgeCodes.EVENT_DELETE);
        event.setPayload("{\"source\":\"expired_at\"}");
        event.setStatus(KnowledgeCodes.OUTBOX_PENDING);
        event.setRetryCount(0);
        event.setNextRetryAt(OffsetDateTime.now());
        outboxMapper.insert(event);

        auditService.record(
                item.getKnowledgeId(), item.getVersionId(), null, 7,
                SYSTEM_OPERATOR, null, item, "expiration-" + event.getEventId());
    }
}
