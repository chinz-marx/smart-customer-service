package com.smartcustomerservice.business.knowledge.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartcustomerservice.business.knowledge.api.dto.ApprovalDecisionRequest;
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
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** 验证人工审批与自动发布验收之间的门禁不会被绕过。 */
@ExtendWith(MockitoExtension.class)
class KnowledgeApprovalServiceTest {
    @Mock private KnowledgeApprovalMapper approvalMapper;
    @Mock private KnowledgeMapper knowledgeMapper;
    @Mock private KnowledgeVersionMapper versionMapper;
    @Mock private KnowledgeOutboxEventMapper outboxMapper;
    @Mock private KnowledgeQueryMapper queryMapper;
    @Mock private KnowledgeAuditService auditService;
    @Mock private ObjectMapper objectMapper;
    @Mock private LearningEvaluationCaseMapper evaluationCaseMapper;
    @Mock private LearningProblemCommandMapper learningProblemMapper;
    @Mock private LearningReleaseEvaluationService releaseEvaluationService;
    @InjectMocks private KnowledgeApprovalService service;

    @Test
    void learningKnowledgeWaitsForEvaluationInsteadOfPublishingImmediately() {
        KnowledgeApproval approval = new KnowledgeApproval();
        approval.setId(30L);
        approval.setKnowledgeId(10L);
        approval.setVersionId(20L);
        approval.setActionType(KnowledgeCodes.ACTION_CREATE);
        approval.setStatus(KnowledgeCodes.APPROVAL_PENDING);
        approval.setApplicantId("applicant-1");
        Knowledge knowledge = new Knowledge();
        knowledge.setId(10L);
        knowledge.setStatus(KnowledgeCodes.KNOWLEDGE_INACTIVE);
        knowledge.setPendingVersionId(20L);
        KnowledgeVersion version = new KnowledgeVersion();
        version.setId(20L);
        version.setKnowledgeId(10L);
        version.setVersionStatus(KnowledgeCodes.VERSION_PENDING);

        when(approvalMapper.selectOne(any())).thenReturn(approval);
        when(knowledgeMapper.selectById(10L)).thenReturn(knowledge);
        when(versionMapper.selectById(20L)).thenReturn(version);
        when(evaluationCaseMapper.countPendingByVersion(20L)).thenReturn(3);

        ApprovalDecisionRequest request = new ApprovalDecisionRequest();
        request.setComment("内容审核通过，等待自动召回验收");
        service.approve(30L, request, "reviewer-1", "request-1");

        assertThat(version.getVersionStatus())
                .isEqualTo(KnowledgeCodes.VERSION_WAITING_EVALUATION);
        assertThat(knowledge.getCurrentVersionId()).isNull();
        verify(evaluationCaseMapper).markPendingEvaluation(20L);
        verify(releaseEvaluationService).createRun(10L, 20L, 30L, 3);
        verify(outboxMapper, never()).insert(any(KnowledgeOutboxEvent.class));
    }
}
