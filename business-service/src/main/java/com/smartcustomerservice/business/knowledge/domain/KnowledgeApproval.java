package com.smartcustomerservice.business.knowledge.domain;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.OffsetDateTime;

/** 新增、修改和停用共用的单级审批单。 */
@Data
@TableName(value = "kb_approval", schema = "business")
public class KnowledgeApproval {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String approvalNo;
    private Long knowledgeId;
    private Long versionId;
    private Integer actionType;
    private Integer status;
    private String applicantId;
    private String approverId;
    private String applicationReason;
    private String approvalComment;
    private String rejectionReason;
    private OffsetDateTime submittedAt;
    private OffsetDateTime finishedAt;
    private OffsetDateTime createdAt;
    private OffsetDateTime updatedAt;
}
