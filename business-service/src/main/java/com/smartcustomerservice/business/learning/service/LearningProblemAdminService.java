package com.smartcustomerservice.business.learning.service;

import com.smartcustomerservice.business.common.error.BusinessErrorCode;
import com.smartcustomerservice.business.common.error.BusinessException;
import com.smartcustomerservice.business.knowledge.api.dto.PageResult;
import com.smartcustomerservice.business.knowledge.api.dto.KnowledgeDetail;
import com.smartcustomerservice.business.knowledge.api.dto.KnowledgeSaveRequest;
import com.smartcustomerservice.business.knowledge.service.KnowledgeAdminService;
import com.smartcustomerservice.business.learning.api.dto.LearningConversionRequest;
import com.smartcustomerservice.business.learning.api.dto.LearningConversionResult;
import com.smartcustomerservice.business.learning.api.dto.ProblemDecisionRequest;
import com.smartcustomerservice.business.learning.api.dto.ProblemDetail;
import com.smartcustomerservice.business.learning.api.dto.ProblemListItem;
import com.smartcustomerservice.business.learning.api.dto.StandardAnswerRequest;
import com.smartcustomerservice.business.learning.domain.LearningProblemCodes;
import com.smartcustomerservice.business.learning.mapper.LearningProblemCommandMapper;
import com.smartcustomerservice.business.learning.mapper.LearningEvaluationCaseMapper;
import com.smartcustomerservice.business.learning.mapper.LearningProblemQueryMapper;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

/** 问题收集后台的查询、标准回答保存和人工审核业务。 */
@Service
@RequiredArgsConstructor
public class LearningProblemAdminService {
    private final LearningProblemQueryMapper queryMapper;
    private final LearningProblemCommandMapper commandMapper;
    private final LearningEvaluationCaseMapper evaluationCaseMapper;
    private final KnowledgeAdminService knowledgeAdminService;

    @Transactional(readOnly = true)
    public PageResult<ProblemListItem> list(
            String keyword, Integer status, Integer sourceType, long page, long size) {
        validateFilter(status, sourceType);
        long safePage = Math.max(1, page);
        long safeSize = Math.min(Math.max(1, size), 100);
        String safeKeyword = StringUtils.trimToNull(keyword);
        return new PageResult<>(
                queryMapper.selectPage(safeKeyword, status, sourceType,
                        safeSize, (safePage - 1) * safeSize),
                queryMapper.countPage(safeKeyword, status, sourceType),
                safePage,
                safeSize);
    }

    @Transactional(readOnly = true)
    public ProblemDetail detail(long id) {
        ProblemListItem problem = requireProblem(queryMapper.selectProblem(id));
        return new ProblemDetail(
                problem,
                queryMapper.selectSamples(id),
                queryMapper.selectReviews(id));
    }

    @Transactional
    public ProblemDetail saveStandardAnswer(
            long id, StandardAnswerRequest request, String operatorId) {
        ProblemListItem locked = requireProblem(commandMapper.selectForUpdate(id));
        requirePendingReview(locked);
        String answer = StringUtils.trim(request.answer());
        int action = StringUtils.isBlank(locked.standardAnswer())
                ? LearningProblemCodes.ACTION_GENERATED
                : LearningProblemCodes.ACTION_EDITED;
        commandMapper.updateAnswer(
                id, answer, StringUtils.trim(request.provider()), StringUtils.trim(request.model()),
                operatorId, OffsetDateTime.now());
        commandMapper.insertReview(
                id, action, locked.status(), locked.status(), answer,
                action == LearningProblemCodes.ACTION_GENERATED ? "LLM生成标准回答草稿" : "人工编辑标准回答草稿",
                operatorId);
        return detail(id);
    }

    /** 人工把尚未达到自动门槛、但已确认值得处理的问题提前送入审核队列。 */
    @Transactional
    public ProblemDetail submitForReview(long id, String operatorId) {
        ProblemListItem locked = requireProblem(commandMapper.selectForUpdate(id));
        if (locked.status() != LearningProblemCodes.STATUS_COLLECTING) {
            throw new BusinessException(BusinessErrorCode.STATE_CONFLICT);
        }
        if (StringUtils.isBlank(locked.problemSummary())
                || StringUtils.isBlank(locked.representativeQuestion())) {
            throw new BusinessException(BusinessErrorCode.LEARNING_PROBLEM_CONTENT_INCOMPLETE);
        }
        if (queryMapper.selectSamples(id).isEmpty()) {
            throw new BusinessException(BusinessErrorCode.LEARNING_PROBLEM_SAMPLE_REQUIRED);
        }
        int changed = commandMapper.submitForReview(id, operatorId);
        if (changed != 1) {
            throw new BusinessException(BusinessErrorCode.STATE_CONFLICT);
        }
        commandMapper.insertReview(
                id, LearningProblemCodes.ACTION_SUBMITTED,
                LearningProblemCodes.STATUS_COLLECTING,
                LearningProblemCodes.STATUS_PENDING_REVIEW,
                locked.standardAnswer(), "人工提交问题审核", operatorId);
        return detail(id);
    }

    @Transactional
    public ProblemDetail approve(long id, ProblemDecisionRequest request, String operatorId) {
        ProblemListItem locked = requireProblem(commandMapper.selectForUpdate(id));
        requirePendingReview(locked);
        if (StringUtils.isBlank(locked.standardAnswer())) {
            throw new BusinessException(BusinessErrorCode.STATE_CONFLICT);
        }
        return finish(
                locked, LearningProblemCodes.STATUS_APPROVED,
                LearningProblemCodes.ACTION_APPROVED,
                StringUtils.trimToNull(request.comment()), null, operatorId);
    }

    @Transactional
    public ProblemDetail reject(long id, ProblemDecisionRequest request, String operatorId) {
        ProblemListItem locked = requireProblem(commandMapper.selectForUpdate(id));
        requirePendingReview(locked);
        String reason = StringUtils.trimToNull(request.rejectionReason());
        if (reason == null) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }
        return finish(
                locked, LearningProblemCodes.STATUS_REJECTED,
                LearningProblemCodes.ACTION_REJECTED,
                StringUtils.trimToNull(request.comment()), reason, operatorId);
    }

    @Transactional
    public ProblemDetail ignore(long id, ProblemDecisionRequest request, String operatorId) {
        ProblemListItem locked = requireProblem(commandMapper.selectForUpdate(id));
        if (locked.status() != LearningProblemCodes.STATUS_COLLECTING
                && locked.status() != LearningProblemCodes.STATUS_PENDING_REVIEW) {
            throw new BusinessException(BusinessErrorCode.STATE_CONFLICT);
        }
        return finish(
                locked, LearningProblemCodes.STATUS_IGNORED,
                LearningProblemCodes.ACTION_IGNORED,
                StringUtils.defaultIfBlank(StringUtils.trimToNull(request.comment()), "人工确认忽略"),
                null, operatorId);
    }

    /**
     * 把人工审核通过的问题一次性转换为知识待审批版本和测试集。
     *
     * <p>知识正文和预期答案强制使用已审核standard_answer，页面只能编辑标题、标签和问法，
     * 从而避免在知识审批前偷偷绕过问题审核修改业务事实。</p>
     */
    @Transactional
    public LearningConversionResult convertToKnowledge(
            long id, LearningConversionRequest request, String operatorId) {
        ProblemListItem locked = requireProblem(commandMapper.selectForUpdate(id));
        if (locked.status() != LearningProblemCodes.STATUS_APPROVED
                || StringUtils.isBlank(locked.standardAnswer())
                || StringUtils.isBlank(locked.intentCode())) {
            throw new BusinessException(BusinessErrorCode.STATE_CONFLICT);
        }
        List<String> standardQuestions = normalizeUnique(request.standardQuestions());
        List<String> testQuestions = normalizeUnique(
                request.testCases().stream().map(LearningConversionRequest.TestCaseDraft::question).toList());
        if (standardQuestions.size() != request.standardQuestions().size()
                || testQuestions.size() != request.testCases().size()) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }
        validateDiversity(request.testCases());
        var realQuestions = queryMapper.selectSamples(id).stream()
                .map(sample -> StringUtils.trim(sample.rootQuestion()))
                .collect(java.util.stream.Collectors.toSet());
        boolean forgedRealSource = request.testCases().stream()
                .anyMatch(item -> item.sourceType() == 1
                        && !realQuestions.contains(StringUtils.trim(item.question())));
        if (forgedRealSource) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }

        KnowledgeSaveRequest knowledgeRequest = new KnowledgeSaveRequest();
        knowledgeRequest.setTitle(StringUtils.trim(request.title()));
        knowledgeRequest.setCategoryId(request.categoryId());
        knowledgeRequest.setContent(StringUtils.trim(locked.standardAnswer()));
        knowledgeRequest.setTags(request.tags());
        knowledgeRequest.setIntentCode(locked.intentCode());
        knowledgeRequest.setEffectiveAt(request.effectiveAt());
        knowledgeRequest.setExpiredAt(request.expiredAt());
        knowledgeRequest.setApplicationReason(
                "由问题收集生成，来源问题：" + locked.problemCode());
        KnowledgeSaveRequest.ChunkDraft chunk = new KnowledgeSaveRequest.ChunkDraft();
        chunk.setContent(StringUtils.trim(locked.standardAnswer()));
        chunk.setQuestions(standardQuestions);
        knowledgeRequest.setChunks(List.of(chunk));

        KnowledgeDetail knowledge = knowledgeAdminService.create(knowledgeRequest, operatorId);
        long knowledgeId = knowledge.knowledge().getId();
        long versionId = knowledge.pendingVersion().getId();
        long approvalId = knowledge.latestApproval().getId();
        for (int index = 0; index < request.testCases().size(); index++) {
            LearningConversionRequest.TestCaseDraft testCase = request.testCases().get(index);
            evaluationCaseMapper.insertCase(
                    "EC-" + compactUuid(), id, knowledgeId, versionId, index,
                    StringUtils.trim(testCase.question()), StringUtils.trim(locked.standardAnswer()),
                    locked.intentCode(), StringUtils.trim(request.provider()),
                    StringUtils.trim(request.model()), operatorId,
                    testCase.caseCategory(), testCase.difficulty(),
                    testCase.sourceType(), testCase.expectedMatch());
        }

        OffsetDateTime now = OffsetDateTime.now();
        int changed = commandMapper.markConverted(
                id, knowledgeId, versionId, approvalId, operatorId, now);
        if (changed != 1) {
            throw new BusinessException(BusinessErrorCode.STATE_CONFLICT);
        }
        commandMapper.insertReview(
                id, LearningProblemCodes.ACTION_CONVERTED,
                LearningProblemCodes.STATUS_APPROVED,
                LearningProblemCodes.STATUS_CONVERTED,
                locked.standardAnswer(),
                "已生成知识草稿、" + testQuestions.size() + "条测试用例并提交知识审批",
                operatorId);
        return new LearningConversionResult(
                id, knowledgeId, versionId, approvalId, testQuestions.size());
    }

    private ProblemDetail finish(
            ProblemListItem locked,
            int targetStatus,
            int action,
            String comment,
            String rejectionReason,
            String operatorId) {
        commandMapper.updateDecision(
                locked.id(), targetStatus, operatorId, OffsetDateTime.now(), comment, rejectionReason);
        commandMapper.insertReview(
                locked.id(), action, locked.status(), targetStatus,
                locked.standardAnswer(),
                rejectionReason == null ? comment : rejectionReason,
                operatorId);
        return detail(locked.id());
    }

    private void requirePendingReview(ProblemListItem problem) {
        if (problem.status() != LearningProblemCodes.STATUS_PENDING_REVIEW) {
            throw new BusinessException(BusinessErrorCode.STATE_CONFLICT);
        }
    }

    private ProblemListItem requireProblem(ProblemListItem problem) {
        if (problem == null) {
            throw new BusinessException(BusinessErrorCode.RESOURCE_NOT_FOUND);
        }
        return problem;
    }

    private void validateFilter(Integer status, Integer sourceType) {
        if (status != null && (status < 0 || status > 5)) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }
        if (sourceType != null && (sourceType < 1 || sourceType > 6)) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }
    }

    private List<String> normalizeUnique(List<String> values) {
        List<String> normalized = values.stream()
                .map(StringUtils::trim)
                .filter(StringUtils::isNotBlank)
                .toList();
        HashSet<String> keys = new HashSet<>();
        for (String value : normalized) {
            String key = value.replaceAll("[\\s？?。！!]+$", "")
                    .toLowerCase(Locale.ROOT);
            if (!keys.add(key)) {
                return List.of();
            }
        }
        return normalized;
    }

    /** 服务端再次校验配额，前端或调用方不能绕过多元测试集要求。 */
    private void validateDiversity(List<LearningConversionRequest.TestCaseDraft> cases) {
        var positiveCategories = cases.stream()
                .filter(LearningConversionRequest.TestCaseDraft::expectedMatch)
                .map(LearningConversionRequest.TestCaseDraft::caseCategory)
                .collect(java.util.stream.Collectors.toSet());
        if (!positiveCategories.containsAll(List.of(
                "conversational", "omitted", "typo", "inverted", "boundary"))) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }
        long negativeCount = cases.stream()
                .filter(item -> !item.expectedMatch()
                        && "hard_negative".equals(item.caseCategory())
                        && item.difficulty() == 3)
                .count();
        if (negativeCount < (cases.size() + 4) / 5) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }
        boolean invalid = cases.stream().anyMatch(item ->
                item.difficulty() < 1 || item.difficulty() > 3
                        || item.sourceType() < 1 || item.sourceType() > 2
                        || ("hard_negative".equals(item.caseCategory()) == item.expectedMatch()));
        if (invalid) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }
    }

    private String compactUuid() {
        return UUID.randomUUID().toString().replace("-", "").toUpperCase(Locale.ROOT);
    }
}
