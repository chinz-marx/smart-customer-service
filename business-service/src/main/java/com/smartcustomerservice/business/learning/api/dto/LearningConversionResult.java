package com.smartcustomerservice.business.learning.api.dto;

/** 提交成功后返回三个稳定ID，前端可以直接跳转知识或审批中心。 */
public record LearningConversionResult(
        long problemId,
        long knowledgeId,
        long versionId,
        long approvalId,
        int testCaseCount) {
}
