package com.smartcustomerservice.business.aftersales.api.dto;

import com.fasterxml.jackson.annotation.JsonPropertyDescription;
import lombok.Builder;
import lombok.Value;

import java.math.BigDecimal;

/** 单个退款商品的金额分摊明细，所有金额单位均为人民币元。 */
@Value
@Builder
public class RefundQuoteItemResult {
    @JsonPropertyDescription("订单商品SKU ID")
    String skuId;
    @JsonPropertyDescription("商品名称")
    String skuName;
    @JsonPropertyDescription("本次试算的退款数量")
    int quantity;
    @JsonPropertyDescription("商品原始金额，即单价乘以退款数量")
    BigDecimal goodsAmount;
    @JsonPropertyDescription("该商品按成交金额比例分摊的满减和优惠券金额")
    BigDecimal discountDeduction;
    @JsonPropertyDescription("该商品按成交金额比例分摊的积分抵扣金额")
    BigDecimal pointsDeduction;
    @JsonPropertyDescription("该商品扣除优惠和积分后的预计可退金额，不包含运费")
    BigDecimal refundableAmount;
}
