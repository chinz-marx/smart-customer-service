package com.smartcustomerservice.business.knowledge.sync;

import com.smartcustomerservice.business.knowledge.mapper.KnowledgeLifecycleMapper;
import com.smartcustomerservice.business.knowledge.service.KnowledgeExpirationService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/** 定时把已过expired_at的知识从线上状态和Redis索引中移除。 */
@Slf4j
@Component
@RequiredArgsConstructor
public class KnowledgeExpirationWorker {
    private final KnowledgeLifecycleMapper lifecycleMapper;
    private final KnowledgeExpirationService expirationService;

    @Scheduled(
            fixedDelayString = "${knowledge.expiration.interval-ms:60000}",
            initialDelayString = "${knowledge.expiration.initial-delay-ms:10000}")
    public void expireKnowledge() {
        for (ExpiredKnowledgeItem item : lifecycleMapper.selectExpiredKnowledge()) {
            try {
                expirationService.expire(item);
            } catch (Exception exception) {
                // 单条失败不能阻止同批其他知识下线，下个周期会继续重试。
                log.error("知识自动失效失败: knowledgeId={}", item.getKnowledgeId(), exception);
            }
        }
    }
}
