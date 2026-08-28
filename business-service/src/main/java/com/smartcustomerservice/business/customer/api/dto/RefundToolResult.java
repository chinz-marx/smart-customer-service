package com.smartcustomerservice.business.customer.api.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Builder;
import lombok.Value;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/** 退款进度查询Tool的结构化返回。 */
@Value
@Builder
public class RefundToolResult {
    boolean found;
    String refundNo;
    String orderId;
    String statusCode;
    String statusText;
    BigDecimal refundAmount;
    @JsonFormat(shape = JsonFormat.Shape.STRING)
    OffsetDateTime expectedAt;
    @JsonFormat(shape = JsonFormat.Shape.STRING)
    OffsetDateTime updatedAt;
    String answer;
}
