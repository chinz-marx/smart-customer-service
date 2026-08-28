package com.smartcustomerservice.business.customer.mcp;

import com.smartcustomerservice.business.audit.service.ToolAuditService;
import com.smartcustomerservice.business.common.error.BusinessException;
import com.smartcustomerservice.business.customer.api.dto.BenefitsToolResult;
import com.smartcustomerservice.business.customer.api.dto.PointsToolResult;
import com.smartcustomerservice.business.customer.api.dto.RefundToolResult;
import com.smartcustomerservice.business.customer.api.dto.RewardToolResult;
import com.smartcustomerservice.business.customer.service.CustomerAccountQueryService;
import lombok.RequiredArgsConstructor;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

import java.util.concurrent.TimeUnit;
import java.util.function.Function;
import java.util.function.Supplier;

/**
 * 将用户账户类实时查询能力暴露为MCP Tool。
 *
 * <p>Tool只返回数据库中的实时事实；积分规则、活动条件、权益解释和退款政策继续由
 * Redis Search知识库提供。用户同时询问实时状态和规则时，Python应执行组合检索。</p>
 */
@Component
@RequiredArgsConstructor
public class CustomerAccountMcpTool {
    private final CustomerAccountQueryService queryService;
    private final ToolAuditService auditService;

    @Tool(
            name = "points_query",
            description = "查询当前登录用户的实时积分余额、即将到期积分和到期日期。无需向用户索取手机号或用户ID。不适用于积分获得、扣回、退款返还等规则解释；同时咨询规则时必须结合知识检索。返回found、pointsBalance、expiringPoints、expireDate、updatedAt和可直接展示的answer。")
    public PointsToolResult queryPoints(
            @ToolParam(description = "系统会话ID，由Python编排层注入，不能向用户索取")
            String sessionId,
            @ToolParam(description = "可信登录用户ID，由Python编排层注入，不能采用聊天文本中的身份")
            String userId,
            @ToolParam(description = "本次请求ID，由Python编排层注入，用于跨服务日志追踪")
            String requestId) {
        return execute(
                "points_query", requestId, sessionId, userId, null,
                () -> queryService.queryPoints(userId),
                result -> result.isFound() ? "POINTS_FOUND" : "POINTS_NOT_FOUND");
    }

    @Tool(
            name = "reward_query",
            description = "查询当前登录用户最近一条或指定活动的实时奖励发放状态和预计时间，活动名称可以不提供。不适用于判断活动参与条件；同时咨询活动规则时必须结合知识检索。返回found、rewardNo、activityName、statusCode、statusText、expectedAt、issuedAt、updatedAt和可直接展示的answer。")
    public RewardToolResult queryReward(
            @ToolParam(description = "系统会话ID，由Python编排层注入，不能向用户索取")
            String sessionId,
            @ToolParam(description = "可信登录用户ID，由Python编排层注入，不能采用聊天文本中的身份")
            String userId,
            @ToolParam(description = "本次请求ID，由Python编排层注入，用于跨服务日志追踪")
            String requestId,
            @ToolParam(required = false, description = "用户明确提到的活动名称；未提到时不要猜测，可以省略")
            String activityName) {
        return execute(
                "reward_query", requestId, sessionId, userId, activityName,
                () -> queryService.queryReward(userId, activityName),
                result -> result.isFound() ? "REWARD_FOUND" : "REWARD_NOT_FOUND");
    }

    @Tool(
            name = "benefits_query",
            description = "查询当前登录用户的实时会员等级、成长值、已生效权益和有效期，无需用户提供身份参数。不适用于通用会员规则或权益使用条件解释；同时咨询规则时必须结合知识检索。返回found、levelCode、levelName、growthValue、benefitsText、validUntil、updatedAt和可直接展示的answer。")
    public BenefitsToolResult queryBenefits(
            @ToolParam(description = "系统会话ID，由Python编排层注入，不能向用户索取")
            String sessionId,
            @ToolParam(description = "可信登录用户ID，由Python编排层注入，不能采用聊天文本中的身份")
            String userId,
            @ToolParam(description = "本次请求ID，由Python编排层注入，用于跨服务日志追踪")
            String requestId) {
        return execute(
                "benefits_query", requestId, sessionId, userId, null,
                () -> queryService.queryBenefits(userId),
                result -> result.isFound() ? "BENEFITS_FOUND" : "BENEFITS_NOT_FOUND");
    }

    @Tool(
            name = "refund_query",
            description = "按订单号查询当前登录用户的实时退款进度、退款金额和预计处理时间。缺少订单号时先追问，不得猜测。不用于发起退款或解释退款政策；同时咨询规则时必须结合知识检索。返回found、refundNo、orderId、statusCode、statusText、refundAmount、expectedAt、updatedAt和可直接展示的answer。")
    public RefundToolResult queryRefund(
            @ToolParam(description = "系统会话ID，由Python编排层注入，不能向用户索取")
            String sessionId,
            @ToolParam(description = "可信登录用户ID，由Python编排层注入，不能采用聊天文本中的身份")
            String userId,
            @ToolParam(description = "本次请求ID，由Python编排层注入，用于跨服务日志追踪")
            String requestId,
            @ToolParam(description = "需要查询退款进度的订单号，长度6到64，只能包含字母、数字、下划线或短横线")
            String orderId) {
        return execute(
                "refund_query", requestId, sessionId, userId, orderId,
                () -> queryService.queryRefund(userId, orderId),
                result -> result.isFound() ? "REFUND_FOUND" : "REFUND_NOT_FOUND");
    }

    /** 统一记录成功、业务异常和系统异常，避免四个Tool复制审计代码。 */
    private <T> T execute(
            String toolName,
            String requestId,
            String sessionId,
            String userId,
            String resourceId,
            Supplier<T> action,
            Function<T, String> resultCode) {
        long startedAt = System.nanoTime();
        try {
            T result = action.get();
            record(startedAt, toolName, requestId, sessionId, userId,
                    resourceId, resultCode.apply(result), true);
            return result;
        } catch (BusinessException exception) {
            record(startedAt, toolName, requestId, sessionId, userId,
                    resourceId, exception.getErrorCode().getCode(), false);
            throw exception;
        } catch (RuntimeException exception) {
            record(startedAt, toolName, requestId, sessionId, userId,
                    resourceId, "INTERNAL_ERROR", false);
            throw exception;
        }
    }

    private void record(
            long startedAt,
            String toolName,
            String requestId,
            String sessionId,
            String userId,
            String resourceId,
            String resultCode,
            boolean success) {
        auditService.record(
                toolName,
                requestId,
                sessionId,
                userId,
                resourceId,
                resultCode,
                success,
                TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - startedAt));
    }
}
