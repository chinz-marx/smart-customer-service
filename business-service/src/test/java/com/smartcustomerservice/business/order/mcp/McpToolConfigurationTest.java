package com.smartcustomerservice.business.order.mcp;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartcustomerservice.business.aftersales.mcp.RefundApplyMcpTool;
import com.smartcustomerservice.business.aftersales.mcp.RefundQuoteMcpTool;
import com.smartcustomerservice.business.customer.mcp.CustomerAccountMcpTool;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

/**
 * 验证 Java Tool 确实会注册到 MCP Server，防止只启动了 MCP 端点却没有发布任何工具。
 */
class McpToolConfigurationTest {

    @Test
    void shouldPublishSevenToolsWithOutputSchemas() {
        OrderMcpTool orderMcpTool = mock(OrderMcpTool.class);
        CustomerAccountMcpTool customerAccountMcpTool = mock(CustomerAccountMcpTool.class);
        RefundQuoteMcpTool refundQuoteMcpTool = mock(RefundQuoteMcpTool.class);
        RefundApplyMcpTool refundApplyMcpTool = mock(RefundApplyMcpTool.class);
        McpToolConfiguration configuration = new McpToolConfiguration();
        ObjectMapper objectMapper = new ObjectMapper();

        List<McpServerFeatures.SyncToolSpecification> specifications =
                configuration.businessMcpToolSpecifications(
                        orderMcpTool,
                        customerAccountMcpTool,
                        refundQuoteMcpTool,
                        refundApplyMcpTool,
                        objectMapper);

        assertThat(specifications)
                .extracting(specification -> specification.tool().name())
                .containsExactlyInAnyOrder(
                        "order_query",
                        "points_query",
                        "reward_query",
                        "benefits_query",
                        "refund_query",
                        "refund_quote",
                        "refund_apply");
        assertThat(specifications)
                .allSatisfy(specification ->
                        assertThat(specification.tool().outputSchema())
                                .containsEntry("type", "object")
                                .containsKey("properties"));

        McpServerFeatures.SyncToolSpecification order = specifications.stream()
                .filter(specification -> "order_query".equals(specification.tool().name()))
                .findFirst()
                .orElseThrow();
        assertThat(order.tool().description())
                .contains("只查询")
                .contains("不适用于")
                .contains("必须结合知识检索")
                .contains("answer");
        assertThat(order.tool().outputSchema().toString()).contains("answer");
        assertThat(order.tool().outputSchema().get("required"))
                .isEqualTo(List.of("found", "answer"));

        // outputSchema非空时，MCP协议要求成功响应必须同时携带structuredContent。
        McpServerFeatures.SyncToolSpecification points = specifications.stream()
                .filter(specification -> "points_query".equals(specification.tool().name()))
                .findFirst()
                .orElseThrow();
        McpSchema.CallToolResult textResult = new McpSchema.CallToolResult(
                List.of(new McpSchema.TextContent(
                        "{\"found\":true,\"pointsBalance\":1280,"
                                + "\"answer\":\"当前可用积分为1280积分。\"}")),
                false);
        McpSchema.CallToolResult callResult =
                configuration.addStructuredContent(textResult, objectMapper);

        assertThat(callResult.isError())
                .withFailMessage("MCP回调执行失败: %s", callResult)
                .isFalse();
        assertThat(callResult.content()).isNotEmpty();
        assertThat(callResult.structuredContent()).isInstanceOf(Map.class);
        @SuppressWarnings("unchecked")
        Map<String, Object> structuredContent =
                (Map<String, Object>) callResult.structuredContent();
        assertThat(structuredContent)
                .containsEntry("pointsBalance", 1280)
                .containsEntry("answer", "当前可用积分为1280积分。");
        @SuppressWarnings("unchecked")
        Map<String, Object> pointsProperties = (Map<String, Object>)
                points.tool().outputSchema().get("properties");
        @SuppressWarnings("unchecked")
        Map<String, Object> pointsBalanceSchema =
                (Map<String, Object>) pointsProperties.get("pointsBalance");
        assertThat(pointsBalanceSchema)
                .containsEntry("description", "当前可用积分余额");

        McpServerFeatures.SyncToolSpecification quote = specifications.stream()
                .filter(specification -> "refund_quote".equals(specification.tool().name()))
                .findFirst()
                .orElseThrow();
        assertThat(quote.tool().description())
                .contains("只读退款试算")
                .contains("不会创建退款单")
                .contains("refund_query");
        assertThat(quote.tool().outputSchema().get("required"))
                .isEqualTo(List.of(
                        "eligible", "orderId", "refundAmount", "goodsAmount",
                        "discountDeduction", "pointsDeduction", "shippingRefund",
                        "itemBreakdown", "availableMethods", "rejectionReasons",
                        "requiredEvidence", "calculatedAt", "answer"));

        McpServerFeatures.SyncToolSpecification apply = specifications.stream()
                .filter(specification -> "refund_apply".equals(specification.tool().name()))
                .findFirst()
                .orElseThrow();
        assertThat(apply.tool().description())
                .contains("明确确认")
                .contains("不得替用户确认")
                .contains("requestId防止重复提交");
        assertThat(apply.tool().outputSchema().get("required"))
                .isEqualTo(List.of(
                        "created", "statusCode", "statusText", "reviewRequired",
                        "refundAmount", "paymentStatus", "answer"));
    }
}
