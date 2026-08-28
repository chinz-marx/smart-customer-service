package com.smartcustomerservice.business.learning.api.dto;

import jakarta.validation.constraints.Size;

/** 审核通过使用comment，驳回使用rejectionReason；Service负责校验动作必填项。 */
public record ProblemDecisionRequest(
        @Size(max = 1000) String comment,
        @Size(max = 1000) String rejectionReason) {
}
