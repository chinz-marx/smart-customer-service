package com.smartcustomerservice.business.audit.service;

import com.smartcustomerservice.business.audit.domain.ToolCallAudit;
import com.smartcustomerservice.business.audit.mapper.ToolCallAuditMapper;
import com.smartcustomerservice.business.order.api.dto.OrderQueryRequest;
import lombok.extern.slf4j.Slf4j;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.core.task.TaskExecutor;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;

/**
 * 记录 Tool 调用审计。
 *
 * <p>独立有界线程池后台入库，排队或入库失败均不阻塞业务结果返回。</p>
 */
@Slf4j
@Service
public class ToolAuditService {
    private static final String ORDER_QUERY_TOOL = "order_query";
    private final ToolCallAuditMapper auditMapper;
    private final TaskExecutor auditExecutor;

    public ToolAuditService(ToolCallAuditMapper auditMapper,
                           @Qualifier("toolAuditExecutor") TaskExecutor auditExecutor) {
        this.auditMapper = auditMapper;
        this.auditExecutor = auditExecutor;
    }

    public void recordOrderQuery(
            String requestId,
            OrderQueryRequest request,
            String resultCode,
            boolean success,
            long durationMs) {
        record(
                ORDER_QUERY_TOOL,
                requestId,
                request.getSessionId(),
                request.getUserId(),
                request.getOrderId(),
                resultCode,
                success,
                durationMs);
    }

    /**
     * 所有Java MCP Tool共用的审计入口。
     * resourceId只保存订单号、奖励编号等业务主键，不保存用户聊天原文或模型提示词。
     */
    public void record(
            String toolName,
            String requestId,
            String sessionId,
            String userId,
            String resourceId,
            String resultCode,
            boolean success,
            long durationMs) {
        ToolCallAudit audit = ToolCallAudit.builder()
                    .requestId(requestId)
                    .sessionId(sessionId)
                    .toolName(toolName)
                    .userId(userId)
                    .resourceId(resourceId)
                    .resultCode(resultCode)
                    .success(success)
                    .durationMs(durationMs)
                    .createdAt(OffsetDateTime.now())
                    .build();
        try {
            auditExecutor.execute(() -> persist(audit));
        } catch (RuntimeException exception) {
            log.warn("Failed to enqueue Tool audit, tool={}, resultCode={}",
                    toolName, resultCode, exception);
        }
    }

    private void persist(ToolCallAudit audit) {
        try (var ignored = MDC.putCloseable("requestId", audit.getRequestId())) {
            auditMapper.insert(audit);
        } catch (RuntimeException exception) {
            // 日志不记录业务主键和用户输入，避免审计失败时产生第二次敏感信息泄露。
            log.warn("Failed to persist Tool audit, tool={}, resultCode={}",
                    audit.getToolName(), audit.getResultCode(), exception);
        }
    }
}
