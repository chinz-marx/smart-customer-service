package com.smartcustomerservice.business.aftersales.mcp;

import com.smartcustomerservice.business.aftersales.api.dto.RefundApplyResult;
import com.smartcustomerservice.business.aftersales.service.RefundApplyService;
import com.smartcustomerservice.business.audit.service.ToolAuditService;
import com.smartcustomerservice.business.common.error.BusinessException;
import lombok.RequiredArgsConstructor;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

import java.util.concurrent.TimeUnit;

/** 把正式退款申请写操作暴露为MCP Tool，并记录完整调用审计。 */
@Component
@RequiredArgsConstructor
public class RefundApplyMcpTool {
    private final RefundApplyService applyService;
    private final ToolAuditService auditService;

    @Tool(
            name = "refund_apply",
            description = "根据refund_quote返回的有效quoteToken创建正式售后退款申请。只有用户在看到试算金额、商品和售后方式后明确确认，confirmed才允许为true；不得替用户确认。该工具不接收退款金额，会在Redis分布式锁和数据库事务内重新校验实时订单与试算结果，使用requestId防止重复提交，并把低风险申请交给异步支付、高风险申请转人工审核。返回created、afterSalesNo、orderId、statusCode、statusText、reviewRequired、refundAmount、paymentStatus和可直接展示的answer。")
    public RefundApplyResult applyRefund(
            @ToolParam(description = "系统会话ID，由Python编排层注入，不能向用户索取")
            String sessionId,
            @ToolParam(description = "可信登录用户ID，由Python编排层注入，不能采用聊天文本中的身份")
            String userId,
            @ToolParam(description = "本次请求ID，由Python编排层注入，同时作为幂等键")
            String requestId,
            @ToolParam(description = "refund_quote成功返回的试算快照令牌；用户无需手工输入")
            String quoteToken,
            @ToolParam(description = "用户确认的售后方式，只能选择试算结果availableMethods中的代码")
            String method,
            @ToolParam(description = "用户是否在当前对话中明确确认提交；没有明确确认必须为false")
            Boolean confirmed) {
        long startedAt = System.nanoTime();
        try {
            RefundApplyResult result = applyService.apply(
                    userId, requestId, quoteToken, method, confirmed);
            record(
                    startedAt, requestId, sessionId, userId, quoteToken,
                    result.isCreated() ? "APPLICATION_CREATED" : result.getStatusCode(), true);
            return result;
        } catch (BusinessException exception) {
            record(
                    startedAt, requestId, sessionId, userId, quoteToken,
                    exception.getErrorCode().getCode(), false);
            throw exception;
        } catch (RuntimeException exception) {
            record(
                    startedAt, requestId, sessionId, userId, quoteToken,
                    "INTERNAL_ERROR", false);
            throw exception;
        }
    }

    private void record(
            long startedAt,
            String requestId,
            String sessionId,
            String userId,
            String quoteToken,
            String resultCode,
            boolean success) {
        auditService.record(
                "refund_apply",
                requestId,
                sessionId,
                userId,
                quoteToken,
                resultCode,
                success,
                TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - startedAt));
    }
}
