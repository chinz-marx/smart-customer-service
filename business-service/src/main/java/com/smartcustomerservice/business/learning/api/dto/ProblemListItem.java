package com.smartcustomerservice.business.learning.api.dto;

import java.time.OffsetDateTime;

/** 问题收集表的一行；sourceType使用与Python一致的1至6数字枚举。 */
public record ProblemListItem(
        long id,
        String problemCode,
        String representativeQuestion,
        String problemSummary,
        String intentCode,
        Double confidence,
        Integer sourceType,
        int occurrenceCount,
        int affectedUserCount,
        int conversationCount,
        int priority,
        int status,
        String standardAnswer,
        String answerProvider,
        String answerModel,
        String answerGeneratedBy,
        OffsetDateTime answerGeneratedAt,
        String reviewedBy,
        OffsetDateTime reviewedAt,
        String reviewComment,
        String rejectionReason,
        int reviewVersion,
        Long convertedKnowledgeId,
        Long convertedVersionId,
        Long convertedApprovalId,
        String convertedBy,
        OffsetDateTime convertedAt,
        OffsetDateTime firstSeenAt,
        OffsetDateTime lastSeenAt) {
}
