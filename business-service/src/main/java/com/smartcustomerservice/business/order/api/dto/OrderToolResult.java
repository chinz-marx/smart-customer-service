package com.smartcustomerservice.business.order.api.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Builder;
import lombok.Value;

import java.time.OffsetDateTime;

/**
 * 订单 Tool 的结构化结果。
 *
 * <p>answer 是经过业务系统确认、可以直接展示的完整话术。Python 收到它后应跳过
 * 最终回答模型，从而减少一次 LLM 调用和等待时间。</p>
 */
@Value
@Builder
public class OrderToolResult {
    boolean found;
    String orderId;
    String statusCode;
    String statusText;
    String logisticsText;
    String expectedProgress;
    @JsonFormat(shape = JsonFormat.Shape.STRING)
    OffsetDateTime updatedAt;
    String answer;
}
