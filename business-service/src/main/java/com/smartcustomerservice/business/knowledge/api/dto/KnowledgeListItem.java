package com.smartcustomerservice.business.knowledge.api.dto;

import lombok.Data;

import java.time.OffsetDateTime;

/** 知识列表只返回表格需要的字段，正文由详情接口按需读取。 */
@Data
public class KnowledgeListItem {
    private Long id;
    private String knowledgeCode;
    private Long categoryId;
    private String categoryName;
    private Integer status;
    private Long versionId;
    private Integer versionNo;
    private Integer versionStatus;
    private String title;
    private String intentCode;
    private String createdBy;
    private String updatedBy;
    private String approverId;
    private String rejectionReason;
    private OffsetDateTime createdAt;
    private OffsetDateTime publishedAt;
}
