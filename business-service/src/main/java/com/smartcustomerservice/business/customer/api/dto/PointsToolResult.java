package com.smartcustomerservice.business.customer.api.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Builder;
import lombok.Value;

import java.time.LocalDate;
import java.time.OffsetDateTime;

/** 积分查询Tool的结构化返回；answer可由Python直接展示。 */
@Value
@Builder
public class PointsToolResult {
    boolean found;
    int pointsBalance;
    int expiringPoints;
    @JsonFormat(shape = JsonFormat.Shape.STRING)
    LocalDate expireDate;
    @JsonFormat(shape = JsonFormat.Shape.STRING)
    OffsetDateTime updatedAt;
    String answer;
}
