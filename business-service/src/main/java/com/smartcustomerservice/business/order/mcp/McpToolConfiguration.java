package com.smartcustomerservice.business.order.mcp;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartcustomerservice.business.aftersales.api.dto.RefundApplyResult;
import com.smartcustomerservice.business.aftersales.api.dto.RefundQuoteResult;
import com.smartcustomerservice.business.aftersales.mcp.RefundApplyMcpTool;
import com.smartcustomerservice.business.aftersales.mcp.RefundQuoteMcpTool;
import com.smartcustomerservice.business.customer.api.dto.BenefitsToolResult;
import com.smartcustomerservice.business.customer.api.dto.PointsToolResult;
import com.smartcustomerservice.business.customer.api.dto.RefundToolResult;
import com.smartcustomerservice.business.customer.api.dto.RewardToolResult;
import com.smartcustomerservice.business.customer.mcp.CustomerAccountMcpTool;
import com.smartcustomerservice.business.order.api.dto.OrderToolResult;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import org.springframework.ai.mcp.McpToolUtils;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.ai.tool.method.MethodToolCallbackProvider;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 注册 Java 业务工具，使 Spring AI MCP Server 能够发现并发布这些工具。
 *
 * <p>{@link OrderMcpTool} 负责订单查询的协议适配和业务调用，本配置只负责把其中带有
 * {@code @Tool} 注解的方法转换为 MCP 工具描述。以后增加新的 Java Tool 时，可以继续把
 * 对应的组件放进 {@code toolObjects(...)}，不需要在 Python 端重复维护 Tool Schema。</p>
 */
@Configuration
public class McpToolConfiguration {
    private static final Map<String, Class<?>> OUTPUT_TYPES = Map.of(
            "order_query", OrderToolResult.class,
            "points_query", PointsToolResult.class,
            "reward_query", RewardToolResult.class,
            "benefits_query", BenefitsToolResult.class,
            "refund_query", RefundToolResult.class,
            "refund_quote", RefundQuoteResult.class,
            "refund_apply", RefundApplyResult.class);

    /**
     * MCP 0.17 的 outputSchema 支持字段说明，但 Spring AI 1.1.2 只会生成字段类型。
     * 这里集中维护业务含义，使 MCP 客户端、调试工具和协议文档看到的是同一份说明。
     */
    private static final Map<String, Map<String, String>> OUTPUT_FIELD_DESCRIPTIONS = Map.of(
            "order_query", Map.of(
                    "found", "是否查询到属于当前登录用户的订单",
                    "orderId", "标准化后的订单号；未命中时仍返回用户提交的订单号",
                    "statusCode", "订单状态代码，供程序判断分支",
                    "statusText", "可向用户展示的订单状态名称",
                    "logisticsText", "当前物流节点或物流状态说明",
                    "expectedProgress", "预计送达或下一处理节点说明",
                    "updatedAt", "订单数据最后更新时间，ISO-8601格式",
                    "answer", "业务系统生成的完整话术；非空时Python可直接返回用户"),
            "points_query", Map.of(
                    "found", "是否查询到当前登录用户的积分账户",
                    "pointsBalance", "当前可用积分余额",
                    "expiringPoints", "临近到期的积分数量",
                    "expireDate", "临近到期积分的到期日期，格式YYYY-MM-DD",
                    "updatedAt", "积分数据最后更新时间，ISO-8601格式",
                    "answer", "业务系统生成的完整话术；非空时Python可直接返回用户"),
            "reward_query", Map.of(
                    "found", "是否查询到匹配的奖励记录",
                    "rewardNo", "奖励业务流水号",
                    "activityName", "奖励所属活动名称",
                    "statusCode", "奖励状态代码，供程序判断分支",
                    "statusText", "可向用户展示的奖励状态名称",
                    "expectedAt", "预计发放时间，未知时为空",
                    "issuedAt", "实际发放时间，尚未发放时为空",
                    "updatedAt", "奖励数据最后更新时间，ISO-8601格式",
                    "answer", "业务系统生成的完整话术；非空时Python可直接返回用户"),
            "benefits_query", Map.of(
                    "found", "是否查询到当前登录用户的会员档案",
                    "levelCode", "会员等级代码，供程序判断分支",
                    "levelName", "可向用户展示的会员等级名称",
                    "growthValue", "当前会员成长值",
                    "benefitsText", "当前已生效的会员权益摘要",
                    "validUntil", "当前会员等级或权益有效期，格式YYYY-MM-DD",
                    "updatedAt", "会员数据最后更新时间，ISO-8601格式",
                    "answer", "业务系统生成的完整话术；非空时Python可直接返回用户"),
            "refund_query", Map.of(
                    "found", "是否查询到该订单对应的退款记录",
                    "refundNo", "退款业务流水号",
                    "orderId", "退款所属的标准化订单号",
                    "statusCode", "退款状态代码，供程序判断分支",
                    "statusText", "可向用户展示的退款状态名称",
                    "refundAmount", "退款金额，单位为元",
                    "expectedAt", "预计完成退款的时间，未知时为空",
                    "updatedAt", "退款数据最后更新时间，ISO-8601格式",
                    "answer", "业务系统生成的完整话术；非空时Python可直接返回用户"),
            "refund_quote", Map.ofEntries(
                    Map.entry("eligible", "是否通过订单状态、售后期限、数量和原因校验"),
                    Map.entry("orderId", "标准化后的订单号"),
                    Map.entry("quoteToken", "正式申请退款必须使用的试算快照令牌"),
                    Map.entry("quoteExpiresAt", "试算快照失效时间，失效后必须重新试算"),
                    Map.entry("refundAmount", "预计退款总额，单位为元"),
                    Map.entry("goodsAmount", "所选退款商品的原始金额合计，单位为元"),
                    Map.entry("discountDeduction", "分摊并扣除的满减和优惠券金额，单位为元"),
                    Map.entry("pointsDeduction", "分摊并扣除的积分抵扣金额，单位为元"),
                    Map.entry("shippingRefund", "预计退还的原订单运费，单位为元"),
                    Map.entry("itemBreakdown", "逐个商品的退款金额和优惠分摊明细"),
                    Map.entry("availableMethods", "可继续选择的售后方式代码"),
                    Map.entry("rejectionReasons", "不可申请或参数不符合规则的原因"),
                    Map.entry("requiredEvidence", "正式申请售后时需要准备的凭证"),
                    Map.entry("calculatedAt", "试算生成时间，ISO-8601格式"),
                    Map.entry("answer", "业务系统生成的完整话术；非空时Python可直接返回用户")),
            "refund_apply", Map.of(
                    "created", "本次调用是否新建售后申请；幂等重试为false",
                    "afterSalesNo", "售后申请编号",
                    "orderId", "售后申请对应的订单号",
                    "statusCode", "售后申请状态代码",
                    "statusText", "可向用户展示的售后状态",
                    "reviewRequired", "是否必须等待人工审核",
                    "refundAmount", "重新校验后的退款金额，单位为元",
                    "paymentStatus", "异步支付状态",
                    "answer", "业务系统生成的完整话术；非空时Python可直接返回用户"));

    /** 不同类型Tool在任何成功业务响应中都必须存在的核心字段。 */
    private static final Map<String, List<String>> REQUIRED_OUTPUT_FIELDS = Map.of(
            "order_query", List.of("found", "answer"),
            "points_query", List.of("found", "answer"),
            "reward_query", List.of("found", "answer"),
            "benefits_query", List.of("found", "answer"),
            "refund_query", List.of("found", "answer"),
            "refund_quote", List.of(
                    "eligible", "orderId", "refundAmount", "goodsAmount",
                    "discountDeduction", "pointsDeduction", "shippingRefund",
                    "itemBreakdown", "availableMethods", "rejectionReasons",
                    "requiredEvidence", "calculatedAt", "answer"),
            "refund_apply", List.of(
                    "created", "statusCode", "statusText", "reviewRequired",
                    "refundAmount", "paymentStatus", "answer"));

    /** 查询未命中或业务时间尚未确定时允许为空的返回字段。 */
    private static final Map<String, Set<String>> NULLABLE_OUTPUT_FIELDS = Map.of(
            "order_query", Set.of(
                    "statusCode", "statusText", "logisticsText", "expectedProgress", "updatedAt"),
            "points_query", Set.of("expireDate", "updatedAt"),
            "reward_query", Set.of(
                    "rewardNo", "activityName", "statusCode", "statusText",
                    "expectedAt", "issuedAt", "updatedAt"),
            "benefits_query", Set.of(
                    "levelCode", "levelName", "benefitsText", "validUntil", "updatedAt"),
            "refund_query", Set.of(
                    "refundNo", "statusCode", "statusText", "refundAmount",
                    "expectedAt", "updatedAt"),
            "refund_quote", Set.of("quoteToken", "quoteExpiresAt"),
            "refund_apply", Set.of("afterSalesNo", "orderId"));

    /**
     * 创建带输入、输出Schema的MCP工具定义。
     *
     * <p>Spring AI MCP Server 会自动收集容器里的 {@link ToolCallbackProvider}，读取工具名、
     * 参数 JSON Schema 和说明，但当前1.1.2版本不会自动生成返回值Schema。这里先复用
     * Spring AI的调用转换器，再补充outputSchema，使Nacos和MCP客户端都能看到完整契约。</p>
     *
     * @param orderMcpTool Spring 创建的订单 MCP 工具组件
     * @param customerAccountMcpTool 积分、奖励、权益和退款工具组件
     * @param refundQuoteMcpTool 复杂退款试算工具组件
     * @param refundApplyMcpTool 正式退款申请写操作工具组件
     * @param objectMapper 将Java返回类型Schema转换为MCP需要的Map
     * @return 七个带完整输入输出定义的同步MCP工具
     */
    @Bean
    public List<McpServerFeatures.SyncToolSpecification> businessMcpToolSpecifications(
            OrderMcpTool orderMcpTool,
            CustomerAccountMcpTool customerAccountMcpTool,
            RefundQuoteMcpTool refundQuoteMcpTool,
            RefundApplyMcpTool refundApplyMcpTool,
            ObjectMapper objectMapper) {
        ToolCallbackProvider provider = MethodToolCallbackProvider.builder()
                .toolObjects(
                        orderMcpTool,
                        customerAccountMcpTool,
                        refundQuoteMcpTool,
                        refundApplyMcpTool)
                .build();
        return Arrays.stream(provider.getToolCallbacks())
                .map(callback -> withOutputSchema(callback, objectMapper))
                .toList();
    }

    private McpServerFeatures.SyncToolSpecification withOutputSchema(
            ToolCallback callback, ObjectMapper objectMapper) {
        McpServerFeatures.SyncToolSpecification base =
                McpToolUtils.toSyncToolSpecification(callback);
        Class<?> outputType = OUTPUT_TYPES.get(callback.getToolDefinition().name());
        if (outputType == null) {
            throw new IllegalStateException(
                    "MCP Tool缺少输出类型定义: " + callback.getToolDefinition().name());
        }

        McpSchema.Tool source = base.tool();
        McpSchema.Tool enriched = new McpSchema.Tool(
                source.name(),
                source.title(),
                source.description(),
                source.inputSchema(),
                generateOutputSchema(outputType, objectMapper),
                source.annotations(),
                source.meta());
        // MCP声明了outputSchema以后，成功响应也必须包含structuredContent。
        // Spring AI 1.1.2默认只返回JSON文本，因此在协议适配层补齐结构化结果。
        return new McpServerFeatures.SyncToolSpecification(
                enriched,
                (exchange, arguments) -> addStructuredContent(
                        base.call().apply(exchange, arguments), objectMapper),
                base.callHandler() == null
                        ? null
                        : (exchange, request) -> addStructuredContent(
                                base.callHandler().apply(exchange, request), objectMapper));
    }

    private Map<String, Object> generateOutputSchema(
            Class<?> outputType, ObjectMapper objectMapper) {
        String schema = org.springframework.ai.util.json.schema.JsonSchemaGenerator
                .generateForType(outputType);
        try {
            Map<String, Object> outputSchema = objectMapper.readValue(
                    schema, new TypeReference<>() {
                    });
            addOutputFieldDescriptions(outputType, outputSchema);
            return outputSchema;
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException(
                    "MCP Tool输出Schema生成失败: " + outputType.getSimpleName(), exception);
        }
    }

    @SuppressWarnings("unchecked")
    private void addOutputFieldDescriptions(
            Class<?> outputType, Map<String, Object> outputSchema) {
        String toolName = OUTPUT_TYPES.entrySet().stream()
                .filter(entry -> entry.getValue().equals(outputType))
                .map(Map.Entry::getKey)
                .findFirst()
                .orElseThrow();
        outputSchema.put("description", toolName + "的结构化业务查询结果");
        // 查询未命中或某个业务阶段尚无时间时，部分详情字段会被省略；
        // 每种Tool只强制自己的稳定核心字段，不能统一假设都包含found。
        outputSchema.put("required", REQUIRED_OUTPUT_FIELDS.get(toolName));
        Object rawProperties = outputSchema.get("properties");
        if (!(rawProperties instanceof Map<?, ?> properties)) {
            return;
        }
        OUTPUT_FIELD_DESCRIPTIONS.getOrDefault(toolName, Map.of())
                .forEach((field, description) -> {
                    Object rawProperty = properties.get(field);
                    if (rawProperty instanceof Map<?, ?> property) {
                        Map<String, Object> writableProperty =
                                (Map<String, Object>) property;
                        writableProperty.put("description", description);
                        if (NULLABLE_OUTPUT_FIELDS
                                .getOrDefault(toolName, Set.of())
                                .contains(field)) {
                            Object type = writableProperty.get("type");
                            if (type instanceof String typeName) {
                                writableProperty.put("type", List.of(typeName, "null"));
                            }
                        }
                    }
                });
    }

    /**
     * 把 Spring AI 返回的 JSON 文本解析为 MCP structuredContent，同时保留文本内容，
     * 兼容只识别旧版文本响应的客户端。
     */
    McpSchema.CallToolResult addStructuredContent(
            McpSchema.CallToolResult result, ObjectMapper objectMapper) {
        if (Boolean.TRUE.equals(result.isError()) || result.structuredContent() != null) {
            return result;
        }
        String json = result.content().stream()
                .filter(McpSchema.TextContent.class::isInstance)
                .map(McpSchema.TextContent.class::cast)
                .map(McpSchema.TextContent::text)
                .findFirst()
                .orElseThrow(() -> new IllegalStateException("MCP Tool成功响应缺少JSON文本"));
        try {
            Map<String, Object> structured = objectMapper.readValue(
                    json, new TypeReference<>() {
                    });
            return new McpSchema.CallToolResult(
                    result.content(), result.isError(), structured, result.meta());
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("MCP Tool成功响应不是合法JSON", exception);
        }
    }
}
