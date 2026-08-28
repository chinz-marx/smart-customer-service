package com.smartcustomerservice.business.learning.service;

import com.smartcustomerservice.business.common.error.BusinessException;
import com.smartcustomerservice.business.learning.api.dto.ProblemListItem;
import com.smartcustomerservice.business.learning.api.dto.ProblemSampleItem;
import com.smartcustomerservice.business.learning.api.dto.StandardAnswerRequest;
import com.smartcustomerservice.business.learning.domain.LearningProblemCodes;
import com.smartcustomerservice.business.learning.mapper.LearningProblemCommandMapper;
import com.smartcustomerservice.business.learning.mapper.LearningProblemQueryMapper;
import com.smartcustomerservice.business.learning.mapper.LearningEvaluationCaseMapper;
import com.smartcustomerservice.business.knowledge.service.KnowledgeAdminService;
import com.smartcustomerservice.business.knowledge.api.dto.KnowledgeDetail;
import com.smartcustomerservice.business.knowledge.api.dto.KnowledgeSaveRequest;
import com.smartcustomerservice.business.knowledge.domain.Knowledge;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeApproval;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeVersion;
import com.smartcustomerservice.business.learning.api.dto.LearningConversionRequest;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.OffsetDateTime;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import org.mockito.ArgumentCaptor;

/** 验证LLM草稿不会绕过待审核状态和人工审批前置条件。 */
@ExtendWith(MockitoExtension.class)
class LearningProblemAdminServiceTest {
    @Mock
    private LearningProblemQueryMapper queryMapper;
    @Mock
    private LearningProblemCommandMapper commandMapper;
    @Mock
    private LearningEvaluationCaseMapper evaluationCaseMapper;
    @Mock
    private KnowledgeAdminService knowledgeAdminService;
    @InjectMocks
    private LearningProblemAdminService service;

    @Test
    void collectingProblemCanBeSubmittedForReviewAndWritesAudit() {
        ProblemListItem collecting = problem(LearningProblemCodes.STATUS_COLLECTING, null);
        ProblemListItem pending = problem(LearningProblemCodes.STATUS_PENDING_REVIEW, null);
        when(commandMapper.selectForUpdate(10L)).thenReturn(collecting);
        when(queryMapper.selectSamples(10L)).thenReturn(List.of(sample()));
        when(commandMapper.submitForReview(10L, "reviewer-001")).thenReturn(1);
        when(queryMapper.selectProblem(10L)).thenReturn(pending);
        when(queryMapper.selectReviews(10L)).thenReturn(List.of());

        var result = service.submitForReview(10L, "reviewer-001");

        assertEquals(LearningProblemCodes.STATUS_PENDING_REVIEW, result.problem().status());
        verify(commandMapper).submitForReview(10L, "reviewer-001");
        verify(commandMapper).insertReview(
                10L, LearningProblemCodes.ACTION_SUBMITTED,
                LearningProblemCodes.STATUS_COLLECTING,
                LearningProblemCodes.STATUS_PENDING_REVIEW,
                null, "人工提交问题审核", "reviewer-001");
    }

    @Test
    void collectingProblemWithoutRealSampleCannotBeSubmitted() {
        when(commandMapper.selectForUpdate(10L)).thenReturn(
                problem(LearningProblemCodes.STATUS_COLLECTING, null));
        when(queryMapper.selectSamples(10L)).thenReturn(List.of());

        assertThrows(BusinessException.class,
                () -> service.submitForReview(10L, "reviewer-001"));
    }

    @Test
    void saveStandardAnswerKeepsPendingStatusAndWritesAudit() {
        ProblemListItem pending = problem(LearningProblemCodes.STATUS_PENDING_REVIEW, null);
        ProblemListItem saved = problem(
                LearningProblemCodes.STATUS_PENDING_REVIEW, "请先查询退款进度，再核对原支付渠道。");
        when(commandMapper.selectForUpdate(10L)).thenReturn(pending);
        when(queryMapper.selectProblem(10L)).thenReturn(saved);
        when(queryMapper.selectSamples(10L)).thenReturn(List.of());
        when(queryMapper.selectReviews(10L)).thenReturn(List.of());

        var result = service.saveStandardAnswer(
                10L,
                new StandardAnswerRequest(saved.standardAnswer(), "doubao", "test-model"),
                "reviewer-001");

        assertEquals(LearningProblemCodes.STATUS_PENDING_REVIEW, result.problem().status());
        verify(commandMapper).updateAnswer(
                eq(10L), eq(saved.standardAnswer()), eq("doubao"), eq("test-model"),
                eq("reviewer-001"), any(OffsetDateTime.class));
        verify(commandMapper).insertReview(
                eq(10L), eq(LearningProblemCodes.ACTION_GENERATED),
                eq(LearningProblemCodes.STATUS_PENDING_REVIEW),
                eq(LearningProblemCodes.STATUS_PENDING_REVIEW),
                eq(saved.standardAnswer()), any(), eq("reviewer-001"));
    }

    @Test
    void approveRejectsProblemWithoutStandardAnswer() {
        when(commandMapper.selectForUpdate(10L)).thenReturn(
                problem(LearningProblemCodes.STATUS_PENDING_REVIEW, null));

        assertThrows(BusinessException.class, () -> service.approve(
                10L,
                new com.smartcustomerservice.business.learning.api.dto.ProblemDecisionRequest(
                        "确认通过", null),
                "reviewer-001"));
    }

    @Test
    void conversionUsesApprovedAnswerAndCreatesPendingCases() {
        ProblemListItem approved = problem(
                LearningProblemCodes.STATUS_APPROVED,
                "退款审核通过后会原路退回，到账时间取决于支付机构。");
        when(commandMapper.selectForUpdate(10L)).thenReturn(approved);
        when(knowledgeAdminService.create(any(KnowledgeSaveRequest.class), eq("reviewer-001")))
                .thenReturn(knowledgeDetail());
        when(commandMapper.markConverted(
                eq(10L), eq(20L), eq(30L), eq(40L), eq("reviewer-001"),
                any(OffsetDateTime.class))).thenReturn(1);
        LearningConversionRequest request = new LearningConversionRequest(
                1L,
                "退款到账时间说明",
                List.of("退款", "到账"),
                OffsetDateTime.now(),
                null,
                List.of("退款多久到", "退款退到哪里", "退款什么时候回来"),
                List.of(
                        testCase("钱怎么没退", "conversational", 1, true),
                        testCase("还没到账", "omitted", 2, true),
                        testCase("退款到帐多久", "typo", 2, true),
                        testCase("审核过了，多久能到账", "inverted", 2, true),
                        testCase("原路退款银行卡何时显示", "boundary", 3, true),
                        testCase("退款到账到底要几天", "conversational", 2, true),
                        testCase("退款失败怎么重新申请", "hard_negative", 3, false),
                        testCase("退货运费谁出", "hard_negative", 3, false)),
                "doubao",
                "test-model");

        var result = service.convertToKnowledge(10L, request, "reviewer-001");

        assertEquals(20L, result.knowledgeId());
        assertEquals(8, result.testCaseCount());
        ArgumentCaptor<KnowledgeSaveRequest> knowledgeRequest =
                ArgumentCaptor.forClass(KnowledgeSaveRequest.class);
        verify(knowledgeAdminService).create(knowledgeRequest.capture(), eq("reviewer-001"));
        assertEquals(approved.standardAnswer(), knowledgeRequest.getValue().getContent());
        verify(evaluationCaseMapper).insertCase(
                any(), eq(10L), eq(20L), eq(30L), eq(0),
                eq("钱怎么没退"), eq(approved.standardAnswer()), eq("refund_query"),
                eq("doubao"), eq("test-model"), eq("reviewer-001"),
                eq("conversational"), eq(1), eq(2), eq(true));
    }

    private LearningConversionRequest.TestCaseDraft testCase(
            String question, String category, int difficulty, boolean expectedMatch) {
        return new LearningConversionRequest.TestCaseDraft(
                question, category, difficulty, 2, expectedMatch);
    }

    private KnowledgeDetail knowledgeDetail() {
        Knowledge knowledge = new Knowledge();
        knowledge.setId(20L);
        KnowledgeVersion version = new KnowledgeVersion();
        version.setId(30L);
        KnowledgeApproval approval = new KnowledgeApproval();
        approval.setId(40L);
        return new KnowledgeDetail(
                knowledge, "退款规则", null, version, approval, List.of());
    }

    private ProblemListItem problem(int status, String answer) {
        OffsetDateTime now = OffsetDateTime.now();
        return new ProblemListItem(
                10L, "PB-TEST-001", "退款什么时候到账", "退款到账延迟",
                "refund_query", 0.91, 1, 4, 3, 4, 2, status,
                answer, answer == null ? null : "doubao",
                answer == null ? null : "test-model", null, null,
                null, null, null, null, 0,
                null, null, null, null, null,
                now, now);
    }

    private ProblemSampleItem sample() {
        return new ProblemSampleItem(
                101L, "退款什么时候到账", null, 1, 0.91,
                "conversation-001", OffsetDateTime.now());
    }
}
