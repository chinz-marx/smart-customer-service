package com.smartcustomerservice.business.order.mcp;

import com.smartcustomerservice.business.audit.service.ToolAuditService;
import com.smartcustomerservice.business.common.error.BusinessException;
import com.smartcustomerservice.business.order.api.dto.OrderQueryRequest;
import com.smartcustomerservice.business.order.api.dto.OrderToolResult;
import com.smartcustomerservice.business.order.service.OrderQueryService;
import lombok.RequiredArgsConstructor;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

import java.util.concurrent.TimeUnit;

/**
 * 把订单业务服务暴露为 MCP Tool。
 *
 * <p>这个适配器只负责协议转换和审计，订单权限、状态规则和数据库查询仍全部位于
 * {@link OrderQueryService}，因此 REST 与 MCP 不会形成两套业务逻辑。</p>
 */
@Component
@RequiredArgsConstructor
public class OrderMcpTool {
    private final OrderQueryService orderQueryService;
    private final ToolAuditService toolAuditService;

    @Tool(
            name = "order_query",
            description = "只查询当前登录用户的一笔订单实时状态、当前物流节点和预计进度。缺少订单号时先追问，不得猜测。不适用于取消、退款、售后、物流异常规则解释；同时咨询规则时必须结合知识检索。返回found、orderId、statusCode、statusText、logisticsText、expectedProgress、updatedAt和可直接展示的answer。")
    public OrderToolResult queryOrder(
            @ToolParam(description = "系统会话ID，由Python编排层注入，不能向用户索取")
            String sessionId,
            @ToolParam(description = "可信登录用户ID，由Python编排层注入，不能采用聊天文本中的身份")
            String userId,
            @ToolParam(description = "本次请求ID，由Python编排层注入，用于跨服务日志追踪")
            String requestId,
            @ToolParam(description = "用户需要查询的订单号，长度6到64，只能包含字母、数字、下划线或短横线")
            String orderId) {
        long startedAt = System.nanoTime();
        OrderQueryRequest request = toRequest(sessionId, userId, orderId);

        try {
            OrderToolResult result = orderQueryService.query(request);
            recordAudit(startedAt, requestId, request,
                    result.isFound() ? "ORDER_FOUND" : "ORDER_NOT_FOUND", true);
            return result;
        } catch (BusinessException exception) {
            recordAudit(startedAt, requestId, request,
                    exception.getErrorCode().getCode(), false);
            throw exception;
        } catch (RuntimeException exception) {
            recordAudit(startedAt, requestId, request, "INTERNAL_ERROR", false);
            throw exception;
        }
    }

    private OrderQueryRequest toRequest(String sessionId, String userId, String orderId) {
        OrderQueryRequest request = new OrderQueryRequest();
        request.setSessionId(sessionId);
        request.setUserId(userId);
        request.setOrderId(orderId);
        return request;
    }

    private void recordAudit(
            long startedAt,
            String requestId,
            OrderQueryRequest request,
            String resultCode,
            boolean success) {
        long durationMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - startedAt);
        toolAuditService.recordOrderQuery(requestId, request, resultCode, success, durationMs);
    }
}
