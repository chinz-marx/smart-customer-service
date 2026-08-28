package com.smartcustomerservice.business.aftersales.api.dto;

import com.fasterxml.jackson.annotation.JsonPropertyDescription;
import lombok.Builder;
import lombok.Value;

import java.math.BigDecimal;

/** 用户确认后创建售后申请的结构化结果。 */
@Value
@Builder
public class RefundApplyResult {
    @JsonPropertyDescription("本次调用是否新建了售后申请；幂等重试返回false")
    boolean created;
    @JsonPropertyDescription("售后申请编号；尚未创建时为空")
    String afterSalesNo;
    @JsonPropertyDescription("售后申请对应的订单号")
    String orderId;
    @JsonPropertyDescription("售后申请状态代码")
    String statusCode;
    @JsonPropertyDescription("可向用户展示的售后状态")
    String statusText;
    @JsonPropertyDescription("是否必须等待人工审核")
    boolean reviewRequired;
    @JsonPropertyDescription("锁定并重新校验后的退款金额，单位为元")
    BigDecimal refundAmount;
    @JsonPropertyDescription("异步支付状态：NOT_STARTED、PENDING、SUCCEEDED或FAILED")
    String paymentStatus;
    @JsonPropertyDescription("业务系统生成的完整话术；非空时Python可以直接返回用户")
    String answer;
}
