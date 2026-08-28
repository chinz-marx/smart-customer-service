package com.smartcustomerservice.business.aftersales.api.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import com.fasterxml.jackson.annotation.JsonPropertyDescription;
import lombok.Builder;
import lombok.Value;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

/** 退款试算的结构化结果；该结果仅供展示，不代表已经创建退款申请。 */
@Value
@Builder(toBuilder = true)
public class RefundQuoteResult {
    @JsonPropertyDescription("是否满足当前退款试算规则并可以继续申请")
    boolean eligible;
    @JsonPropertyDescription("标准化后的订单号")
    String orderId;
    @JsonPropertyDescription("试算快照令牌；只有eligible=true时返回，正式申请退款必须携带")
    String quoteToken;
    @JsonPropertyDescription("quoteToken失效时间，ISO-8601格式；失效后必须重新试算")
    @JsonFormat(shape = JsonFormat.Shape.STRING)
    OffsetDateTime quoteExpiresAt;
    @JsonPropertyDescription("预计退款总额：商品可退金额加退还运费")
    BigDecimal refundAmount;
    @JsonPropertyDescription("所选退款商品的原始金额合计")
    BigDecimal goodsAmount;
    @JsonPropertyDescription("按比例分摊并从退款中扣除的满减和优惠券金额")
    BigDecimal discountDeduction;
    @JsonPropertyDescription("按比例分摊并从退款中扣除的积分抵扣金额")
    BigDecimal pointsDeduction;
    @JsonPropertyDescription("本次预计退还的原订单运费")
    BigDecimal shippingRefund;
    @JsonPropertyDescription("每个退款商品的金额分摊明细")
    List<RefundQuoteItemResult> itemBreakdown;
    @JsonPropertyDescription("允许继续选择的售后方式代码")
    List<String> availableMethods;
    @JsonPropertyDescription("不允许申请或参数不符合规则的原因；可申请时为空数组")
    List<String> rejectionReasons;
    @JsonPropertyDescription("正式申请售后时需要准备的凭证")
    List<String> requiredEvidence;
    @JsonPropertyDescription("试算生成时间，ISO-8601格式")
    @JsonFormat(shape = JsonFormat.Shape.STRING)
    OffsetDateTime calculatedAt;
    @JsonPropertyDescription("业务系统生成的完整话术；非空时Python可以直接返回用户")
    String answer;
}
