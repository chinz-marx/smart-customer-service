package com.smartcustomerservice.business.aftersales.api.dto;

import com.fasterxml.jackson.annotation.JsonPropertyDescription;
import lombok.Data;

/** 用户希望退款的一项商品及数量，由LLM从用户表达中提取。 */
@Data
public class RefundQuoteItemInput {
    @JsonPropertyDescription("订单商品SKU ID，例如SKU_PHONE_CASE")
    private String skuId;

    @JsonPropertyDescription("本次希望退款的商品数量，必须大于0且不能超过剩余可退数量")
    private Integer quantity;
}
