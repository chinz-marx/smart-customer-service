package com.smartcustomerservice.business.knowledge.api.dto;

import lombok.Data;

import java.time.OffsetDateTime;

/** 审批中心列表项。 */
@Data
public class ApprovalListItem {
    private Long approvalId;
    private String approvalNo;
    private Long knowledgeId;
    private Long versionId;
    private Integer actionType;
    private String title;
    private String categoryName;
    private Integer versionNo;
    private String applicantId;
    private String applicationReason;
    private OffsetDateTime submittedAt;
}
