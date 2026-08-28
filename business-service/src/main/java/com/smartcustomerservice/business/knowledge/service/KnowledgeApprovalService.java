package com.smartcustomerservice.business.knowledge.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartcustomerservice.business.common.error.BusinessErrorCode;
import com.smartcustomerservice.business.common.error.BusinessException;
import com.smartcustomerservice.business.knowledge.api.dto.ApprovalDecisionRequest;
import com.smartcustomerservice.business.knowledge.api.dto.ApprovalListItem;
import com.smartcustomerservice.business.knowledge.api.dto.PageResult;
import com.smartcustomerservice.business.knowledge.domain.Knowledge;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeApproval;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeCodes;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeOutboxEvent;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeVersion;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeApprovalMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeOutboxEventMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeQueryMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeVersionMapper;
import com.smartcustomerservice.business.learning.mapper.LearningEvaluationCaseMapper;
import com.smartcustomerservice.business.learning.mapper.LearningProblemCommandMapper;
import com.smartcustomerservice.business.learning.service.LearningReleaseEvaluationService;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.Map;
import java.util.UUID;

/** 单级人工审批：发布事务成功后再由 Outbox 异步同步 Redis。 */
@Service
@RequiredArgsConstructor
public class KnowledgeApprovalService {
    private final KnowledgeApprovalMapper approvalMapper;
    private final KnowledgeMapper knowledgeMapper;
    private final KnowledgeVersionMapper versionMapper;
    private final KnowledgeOutboxEventMapper outboxMapper;
    private final KnowledgeQueryMapper queryMapper;
    private final KnowledgeAuditService auditService;
    private final ObjectMapper objectMapper;
    private final LearningEvaluationCaseMapper evaluationCaseMapper;
    private final LearningProblemCommandMapper learningProblemMapper;
    private final LearningReleaseEvaluationService releaseEvaluationService;

    @Transactional(readOnly = true)
    public PageResult<ApprovalListItem> listPending(long page, long size) {
        long safePage = Math.max(1, page);
        long safeSize = Math.min(Math.max(1, size), 100);
        return new PageResult<>(
                queryMapper.selectPendingApprovals(safeSize, (safePage - 1) * safeSize),
                queryMapper.countPendingApprovals(), safePage, safeSize);
    }

    @Transactional
    public KnowledgeApproval approve(
            long approvalId, ApprovalDecisionRequest request, String operatorId, String requestId) {
        KnowledgeApproval approval = lockPendingApproval(approvalId);
        preventSelfApproval(approval, operatorId);
        Knowledge knowledge = requireKnowledge(approval.getKnowledgeId());
        KnowledgeVersion target = requireVersion(approval.getVersionId());

        int evaluationCases = approval.getActionType() == KnowledgeCodes.ACTION_DISABLE
                ? 0 : evaluationCaseMapper.countPendingByVersion(target.getId());
        if (evaluationCases > 0) {
            // 问题学习生成的候选知识必须先通过真实检索验收，人工审批本身不代表已经上线。
            target.setVersionStatus(KnowledgeCodes.VERSION_WAITING_EVALUATION);
            target.setUpdatedBy(operatorId);
            versionMapper.updateById(target);
            knowledge.setUpdatedBy(operatorId);
            knowledgeMapper.updateById(knowledge);
            finish(approval, KnowledgeCodes.APPROVAL_APPROVED,
                    operatorId, request.getComment(), null);
            evaluationCaseMapper.markPendingEvaluation(target.getId());
            releaseEvaluationService.createRun(
                    knowledge.getId(), target.getId(), approval.getId(), evaluationCases);
            auditService.record(knowledge.getId(), target.getId(), approval.getId(), 4,
                    operatorId, null, approval, requestId);
            return approval;
        }

        if (approval.getActionType() == KnowledgeCodes.ACTION_DISABLE) {
            knowledge.setStatus(KnowledgeCodes.KNOWLEDGE_INACTIVE);
            knowledge.setPendingVersionId(null);
            target.setVersionStatus(KnowledgeCodes.VERSION_ARCHIVED);
            versionMapper.updateById(target);
            createOutbox(knowledge, target, KnowledgeCodes.EVENT_DELETE);
        } else {
            if (knowledge.getCurrentVersionId() != null
                    && !knowledge.getCurrentVersionId().equals(target.getId())) {
                KnowledgeVersion old = versionMapper.selectById(knowledge.getCurrentVersionId());
                old.setVersionStatus(KnowledgeCodes.VERSION_ARCHIVED);
                old.setUpdatedBy(operatorId);
                versionMapper.updateById(old);
            }
            target.setVersionStatus(KnowledgeCodes.VERSION_PUBLISHED);
            target.setPublishedAt(OffsetDateTime.now());
            target.setUpdatedBy(operatorId);
            versionMapper.updateById(target);
            knowledge.setCurrentVersionId(target.getId());
            knowledge.setPendingVersionId(null);
            knowledge.setStatus(KnowledgeCodes.KNOWLEDGE_ACTIVE);
            createOutbox(knowledge, target, KnowledgeCodes.EVENT_UPSERT);
        }

        knowledge.setUpdatedBy(operatorId);
        knowledgeMapper.updateById(knowledge);
        finish(approval, KnowledgeCodes.APPROVAL_APPROVED, operatorId, request.getComment(), null);
        // 问题学习生成的测试集只有在知识审批通过后才能进入正式回归集。
        auditService.record(knowledge.getId(), target.getId(), approval.getId(), 4,
                operatorId, null, approval, requestId);
        return approval;
    }

    @Transactional
    public KnowledgeApproval reject(
            long approvalId, ApprovalDecisionRequest request, String operatorId, String requestId) {
        if (StringUtils.isBlank(request.getRejectionReason())) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }
        KnowledgeApproval approval = lockPendingApproval(approvalId);
        preventSelfApproval(approval, operatorId);
        Knowledge knowledge = requireKnowledge(approval.getKnowledgeId());
        KnowledgeVersion target = requireVersion(approval.getVersionId());
        if (approval.getActionType() != KnowledgeCodes.ACTION_DISABLE) {
            target.setVersionStatus(KnowledgeCodes.VERSION_REJECTED);
            target.setUpdatedBy(operatorId);
            versionMapper.updateById(target);
        }
        knowledge.setPendingVersionId(null);
        knowledge.setUpdatedBy(operatorId);
        knowledgeMapper.updateById(knowledge);
        finish(approval, KnowledgeCodes.APPROVAL_REJECTED, operatorId,
                request.getComment(), StringUtils.trim(request.getRejectionReason()));
        if (approval.getActionType() == KnowledgeCodes.ACTION_CREATE) {
            rejectLearningPackage(target.getId(), operatorId);
        }
        auditService.record(knowledge.getId(), target.getId(), approval.getId(), 5,
                operatorId, null, approval, requestId);
        return approval;
    }

    @Transactional
    public KnowledgeApproval cancel(long approvalId, String operatorId, String requestId) {
        KnowledgeApproval approval = lockPendingApproval(approvalId);
        if (!operatorId.equals(approval.getApplicantId())) {
            throw new BusinessException(BusinessErrorCode.OPERATION_FORBIDDEN);
        }
        Knowledge knowledge = requireKnowledge(approval.getKnowledgeId());
        KnowledgeVersion target = requireVersion(approval.getVersionId());
        if (approval.getActionType() != KnowledgeCodes.ACTION_DISABLE) {
            target.setVersionStatus(KnowledgeCodes.VERSION_REJECTED);
            versionMapper.updateById(target);
        }
        knowledge.setPendingVersionId(null);
        knowledge.setUpdatedBy(operatorId);
        knowledgeMapper.updateById(knowledge);
        finish(approval, KnowledgeCodes.APPROVAL_CANCELED, operatorId, "申请人撤销", null);
        if (approval.getActionType() == KnowledgeCodes.ACTION_CREATE) {
            rejectLearningPackage(target.getId(), operatorId);
        }
        auditService.record(knowledge.getId(), target.getId(), approval.getId(), 6,
                operatorId, null, approval, requestId);
        return approval;
    }

    private KnowledgeApproval lockPendingApproval(long id) {
        KnowledgeApproval approval = approvalMapper.selectOne(
                Wrappers.<KnowledgeApproval>lambdaQuery()
                        .eq(KnowledgeApproval::getId, id)
                        .last("FOR UPDATE"));
        if (approval == null) {
            throw new BusinessException(BusinessErrorCode.RESOURCE_NOT_FOUND);
        }
        if (!Integer.valueOf(KnowledgeCodes.APPROVAL_PENDING).equals(approval.getStatus())) {
            throw new BusinessException(BusinessErrorCode.STATE_CONFLICT);
        }
        return approval;
    }

    private void preventSelfApproval(KnowledgeApproval approval, String operatorId) {
        if (operatorId.equals(approval.getApplicantId())) {
            throw new BusinessException(BusinessErrorCode.OPERATION_FORBIDDEN);
        }
    }

    private void finish(
            KnowledgeApproval approval, int status, String approverId,
            String comment, String rejectionReason) {
        approval.setStatus(status);
        approval.setApproverId(approverId);
        approval.setApprovalComment(StringUtils.trimToNull(comment));
        approval.setRejectionReason(rejectionReason);
        approval.setFinishedAt(OffsetDateTime.now());
        approvalMapper.updateById(approval);
    }

    private void createOutbox(Knowledge knowledge, KnowledgeVersion version, int eventType) {
        KnowledgeOutboxEvent event = new KnowledgeOutboxEvent();
        event.setEventId(UUID.randomUUID().toString());
        event.setKnowledgeId(knowledge.getId());
        event.setVersionId(version.getId());
        event.setEventType(eventType);
        event.setPayload(toJson(Map.of("knowledgeCode", knowledge.getKnowledgeCode())));
        event.setStatus(KnowledgeCodes.OUTBOX_PENDING);
        event.setRetryCount(0);
        OffsetDateTime now = OffsetDateTime.now();
        // 未来生效的版本保留为待处理事件，到effective_at后再进入Redis。
        event.setNextRetryAt(eventType == KnowledgeCodes.EVENT_UPSERT
                && version.getEffectiveAt().isAfter(now)
                ? version.getEffectiveAt() : now);
        outboxMapper.insert(event);
    }

    private void rejectLearningPackage(long versionId, String operatorId) {
        OffsetDateTime now = OffsetDateTime.now();
        evaluationCaseMapper.rejectByVersion(versionId, operatorId, now);
        // 知识未发布时恢复原问题，审核员修订后可以重新生成另一份草稿。
        learningProblemMapper.restoreApprovedByVersion(versionId, operatorId);
    }

    private String toJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Outbox消息序列化失败", exception);
        }
    }

    private Knowledge requireKnowledge(long id) {
        Knowledge value = knowledgeMapper.selectById(id);
        if (value == null) {
            throw new BusinessException(BusinessErrorCode.RESOURCE_NOT_FOUND);
        }
        return value;
    }

    private KnowledgeVersion requireVersion(long id) {
        KnowledgeVersion value = versionMapper.selectById(id);
        if (value == null) {
            throw new BusinessException(BusinessErrorCode.RESOURCE_NOT_FOUND);
        }
        return value;
    }
}
