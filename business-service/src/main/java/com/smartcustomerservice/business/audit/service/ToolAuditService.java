package com.smartcustomerservice.business.audit.service;

import com.smartcustomerservice.business.audit.domain.ToolCallAudit;
import com.smartcustomerservice.business.audit.mapper.ToolCallAuditMapper;
import com.smartcustomerservice.business.order.api.dto.OrderQueryRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

/**
 * 记录 Tool 调用审计。
 *
 * <p>审计写入失败不能覆盖真实订单查询结果，因此这里捕获异常并报警，后续可将审计
 * 改成消息队列异步写入。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ToolAuditService {
    private static final String ORDER_QUERY_TOOL = "order_query";
    private final ToolCallAuditMapper auditMapper;

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
        try {
            auditMapper.insert(ToolCallAudit.builder()
                    .requestId(requestId)
                    .sessionId(sessionId)
                    .toolName(toolName)
                    .userId(userId)
                    .resourceId(resourceId)
                    .resultCode(resultCode)
                    .success(success)
                    .durationMs(durationMs)
                    .build());
        } catch (RuntimeException exception) {
            // 日志不记录业务主键和用户输入，避免审计失败时产生第二次敏感信息泄露。
            log.warn("Failed to persist Tool audit, tool={}, resultCode={}",
                    toolName, resultCode, exception);
        }
    }
}
