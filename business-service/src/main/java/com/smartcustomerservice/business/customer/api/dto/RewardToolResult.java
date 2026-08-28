package com.smartcustomerservice.business.customer.api.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Builder;
import lombok.Value;

import java.time.OffsetDateTime;

/** 活动奖励查询Tool的结构化返回。 */
@Value
@Builder
public class RewardToolResult {
    boolean found;
    String rewardNo;
    String activityName;
    String statusCode;
    String statusText;
    @JsonFormat(shape = JsonFormat.Shape.STRING)
    OffsetDateTime expectedAt;
    @JsonFormat(shape = JsonFormat.Shape.STRING)
    OffsetDateTime issuedAt;
    @JsonFormat(shape = JsonFormat.Shape.STRING)
    OffsetDateTime updatedAt;
    String answer;
}
