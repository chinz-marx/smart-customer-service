package com.smartcustomerservice.business.knowledge.api.dto;

import jakarta.validation.constraints.Size;
import lombok.Data;

/** 审批意见和驳回原因分开保存，便于后台明确展示。 */
@Data
public class ApprovalDecisionRequest {
    @Size(max = 1000, message = "审批意见不能超过1000个字符")
    private String comment;

    @Size(max = 1000, message = "驳回原因不能超过1000个字符")
    private String rejectionReason;
}
