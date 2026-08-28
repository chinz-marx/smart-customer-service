package com.smartcustomerservice.business.aftersales.mcp;

import com.smartcustomerservice.business.aftersales.api.dto.RefundQuoteItemInput;
import com.smartcustomerservice.business.aftersales.api.dto.RefundQuoteResult;
import com.smartcustomerservice.business.aftersales.service.RefundQuoteService;
import com.smartcustomerservice.business.audit.service.ToolAuditService;
import com.smartcustomerservice.business.common.error.BusinessException;
import lombok.RequiredArgsConstructor;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.concurrent.TimeUnit;

/** 把只读退款试算能力暴露为MCP Tool，并统一记录跨服务审计。 */
@Component
@RequiredArgsConstructor
public class RefundQuoteMcpTool {
    private final RefundQuoteService refundQuoteService;
    private final ToolAuditService auditService;

    @Tool(
            name = "refund_quote",
            description = "在正式申请退款前，对指定订单商品进行只读退款试算。它会校验订单状态、售后期限、可退数量，按成交金额比例分摊满减、优惠券和积分抵扣，并判断运费、售后方式及所需凭证。该工具不会创建退款单或调用支付；查询已有退款进度应使用refund_query，解释退款政策时应结合知识检索。返回eligible、orderId、refundAmount、goodsAmount、discountDeduction、pointsDeduction、shippingRefund、itemBreakdown、availableMethods、rejectionReasons、requiredEvidence、calculatedAt和可直接展示的answer。")
    public RefundQuoteResult quoteRefund(
            @ToolParam(description = "系统会话ID，由Python编排层注入，不能向用户索取")
            String sessionId,
            @ToolParam(description = "可信登录用户ID，由Python编排层注入，不能采用聊天文本中的身份")
            String userId,
            @ToolParam(description = "本次请求ID，由Python编排层注入，用于跨服务日志追踪")
            String requestId,
            @ToolParam(description = "需要进行退款试算的订单号")
            String orderId,
            @ToolParam(description = "退款商品列表，每项必须提供skuId和quantity；缺少商品或数量时先追问用户")
            List<RefundQuoteItemInput> refundItems,
            @ToolParam(description = "标准退款原因代码，只能是QUALITY_ISSUE、DAMAGED、WRONG_ITEM、NOT_RECEIVED或PERSONAL_REASON")
            String reasonCode,
            @ToolParam(description = "用户是否已经收到商品；必须根据用户回答填写，不得猜测")
            Boolean received) {
        long startedAt = System.nanoTime();
        try {
            RefundQuoteResult result = refundQuoteService.quote(
                    userId, orderId, refundItems, reasonCode, received);
            record(
                    startedAt, requestId, sessionId, userId, orderId,
                    result.isEligible() ? "QUOTE_ELIGIBLE" : "QUOTE_REJECTED", true);
            return result;
        } catch (BusinessException exception) {
            record(
                    startedAt, requestId, sessionId, userId, orderId,
                    exception.getErrorCode().getCode(), false);
            throw exception;
        } catch (RuntimeException exception) {
            record(
                    startedAt, requestId, sessionId, userId, orderId,
                    "INTERNAL_ERROR", false);
            throw exception;
        }
    }

    private void record(
            long startedAt,
            String requestId,
            String sessionId,
            String userId,
            String orderId,
            String resultCode,
            boolean success) {
        auditService.record(
                "refund_quote",
                requestId,
                sessionId,
                userId,
                orderId,
                resultCode,
                success,
                TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - startedAt));
    }
}
