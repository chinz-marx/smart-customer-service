package com.smartcustomerservice.business.customer.api.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Builder;
import lombok.Value;

import java.time.LocalDate;
import java.time.OffsetDateTime;

/** 会员权益查询Tool的结构化返回。 */
@Value
@Builder
public class BenefitsToolResult {
    boolean found;
    String levelCode;
    String levelName;
    int growthValue;
    String benefitsText;
    @JsonFormat(shape = JsonFormat.Shape.STRING)
    LocalDate validUntil;
    @JsonFormat(shape = JsonFormat.Shape.STRING)
    OffsetDateTime updatedAt;
    String answer;
}
