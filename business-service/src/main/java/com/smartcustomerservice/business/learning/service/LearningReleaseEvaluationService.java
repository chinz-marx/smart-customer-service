package com.smartcustomerservice.business.learning.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartcustomerservice.business.common.error.BusinessErrorCode;
import com.smartcustomerservice.business.common.error.BusinessException;
import com.smartcustomerservice.business.knowledge.api.dto.PageResult;
import com.smartcustomerservice.business.knowledge.domain.Knowledge;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeCodes;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeOutboxEvent;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeVersion;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeOutboxEventMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeVersionMapper;
import com.smartcustomerservice.business.learning.api.dto.EvaluationRunListItem;
import com.smartcustomerservice.business.learning.api.dto.EvaluationRunCaseResultItem;
import com.smartcustomerservice.business.learning.domain.LearningEvaluationRun;
import com.smartcustomerservice.business.learning.domain.LearningProblemCodes;
import com.smartcustomerservice.business.learning.mapper.LearningEvaluationCaseMapper;
import com.smartcustomerservice.business.learning.mapper.LearningEvaluationResultMapper;
import com.smartcustomerservice.business.learning.mapper.LearningEvaluationRunMapper;
import com.smartcustomerservice.business.learning.mapper.LearningProblemCommandMapper;
import com.smartcustomerservice.business.learning.sync.ReleaseEvaluationResult;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 管理自动发布验收批次。
 *
 * <p>网络评测不放在本类事务中；Worker 先调用 claim 提交认领，再访问 Python，最后调用
 * complete 或 failSystem。这样模型超时不会占用数据库行锁。</p>
 */
@Service
@RequiredArgsConstructor
public class LearningReleaseEvaluationService {
    private static final String SYSTEM_OPERATOR = "system-evaluator";

    private final LearningEvaluationRunMapper runMapper;
    private final LearningEvaluationResultMapper resultMapper;
    private final LearningEvaluationCaseMapper caseMapper;
    private final LearningProblemCommandMapper problemMapper;
    private final KnowledgeMapper knowledgeMapper;
    private final KnowledgeVersionMapper versionMapper;
    private final KnowledgeOutboxEventMapper outboxMapper;
    private final ObjectMapper objectMapper;

    /** 人工知识审批通过时创建唯一验收批次。 */
    @Transactional
    public LearningEvaluationRun createRun(
            long knowledgeId, long versionId, long approvalId, int totalCases) {
        Long problemId = caseMapper.selectProblemIdByVersion(versionId);
        if (problemId == null || totalCases <= 0) {
            throw new BusinessException(BusinessErrorCode.STATE_CONFLICT);
        }
        LearningEvaluationRun run = new LearningEvaluationRun();
        run.setRunNo("EV-" + UUID.randomUUID().toString().replace("-", "").toUpperCase());
        run.setProblemId(problemId);
        run.setKnowledgeId(knowledgeId);
        run.setVersionId(versionId);
        run.setApprovalId(approvalId);
        run.setStatus(LearningProblemCodes.EVALUATION_PENDING);
        run.setRetryCount(0);
        run.setNextRetryAt(OffsetDateTime.now());
        run.setTotalCases(totalCases);
        runMapper.insert(run);
        return run;
    }

    @Transactional(readOnly = true)
    public List<LearningEvaluationRun> findReady(int limit) {
        OffsetDateTime now = OffsetDateTime.now();
        return runMapper.selectReady(now, now.minusMinutes(10), Math.min(Math.max(limit, 1), 20));
    }

    /** 使用状态和上次处理时间做乐观认领，确保多实例中只有一个执行者成功。 */
    @Transactional
    public boolean claim(LearningEvaluationRun run) {
        var update = Wrappers.<LearningEvaluationRun>lambdaUpdate()
                .set(LearningEvaluationRun::getStatus, LearningProblemCodes.EVALUATION_PROCESSING)
                .set(LearningEvaluationRun::getStartedAt, OffsetDateTime.now())
                .set(LearningEvaluationRun::getProcessedAt, OffsetDateTime.now())
                .eq(LearningEvaluationRun::getId, run.getId())
                .eq(LearningEvaluationRun::getStatus, run.getStatus());
        if (run.getProcessedAt() == null) {
            update.isNull(LearningEvaluationRun::getProcessedAt);
        } else {
            update.eq(LearningEvaluationRun::getProcessedAt, run.getProcessedAt());
        }
        return runMapper.update(null, update) == 1;
    }

    /** 保存逐用例结果，并在同一事务内决定正式发布或阻断候选版本。 */
    @Transactional
    public void complete(long runId, ReleaseEvaluationResult result) {
        LearningEvaluationRun run = lockProcessing(runId);
        if (result.runId() != runId || result.totalCases() != run.getTotalCases()
                || result.cases() == null || result.cases().size() != run.getTotalCases()) {
            throw new IllegalStateException("Python返回的验收批次或用例数量不一致");
        }
        for (ReleaseEvaluationResult.CaseResult item : result.cases()) {
            resultMapper.upsert(
                    runId, item.caseId(), item.expectedMatch(), item.passedAt1(), item.passedAt3(),
                    item.passedThreshold(), item.topKnowledgeId(), item.topVersionId(),
                    item.topChunkNo(), item.topDistance(), item.latencyMs(),
                    StringUtils.abbreviate(item.errorMessage(), 1000));
        }

        copyMetrics(run, result);
        OffsetDateTime now = OffsetDateTime.now();
        if (result.passed()) {
            publishCandidate(run, now);
            run.setStatus(LearningProblemCodes.EVALUATION_PASSED);
        } else {
            rejectCandidate(run, now);
            run.setStatus(LearningProblemCodes.EVALUATION_FAILED);
        }
        run.setMetrics(toJson(Map.of(
                "passed", result.passed(),
                "recallAt1", result.recallAt1(),
                "recallAt3", result.recallAt3(),
                "thresholdRecall", result.thresholdRecall(),
                "hardNegativeFalsePositiveRate", result.hardNegativeFalsePositiveRate())));
        run.setErrorMessage(null);
        run.setFinishedAt(now);
        run.setProcessedAt(now);
        runMapper.updateById(run);
    }

    /** 系统错误采用指数退避；超过重试上限后保持知识未发布并标记系统阻断。 */
    @Transactional
    public void failSystem(long runId, Exception exception, int maxRetries) {
        LearningEvaluationRun run = lockProcessing(runId);
        int retries = run.getRetryCount() + 1;
        run.setRetryCount(retries);
        run.setErrorMessage(StringUtils.abbreviate(exception.getMessage(), 1000));
        run.setProcessedAt(null);
        if (retries >= Math.max(1, maxRetries)) {
            run.setStatus(LearningProblemCodes.EVALUATION_SYSTEM_FAILED);
            run.setFinishedAt(OffsetDateTime.now());
        } else {
            long delaySeconds = Math.min(300, 1L << Math.min(retries, 8));
            run.setStatus(LearningProblemCodes.EVALUATION_PENDING);
            run.setNextRetryAt(OffsetDateTime.now().plusSeconds(delaySeconds));
        }
        runMapper.updateById(run);
    }

    @Transactional(readOnly = true)
    public PageResult<EvaluationRunListItem> list(long page, long size) {
        long safePage = Math.max(1, page);
        long safeSize = Math.min(Math.max(1, size), 100);
        return new PageResult<>(
                runMapper.selectPage(safeSize, (safePage - 1) * safeSize),
                runMapper.countAll(), safePage, safeSize);
    }

    @Transactional(readOnly = true)
    public List<EvaluationRunCaseResultItem> listResults(long runId) {
        if (runMapper.selectById(runId) == null) {
            throw new BusinessException(BusinessErrorCode.RESOURCE_NOT_FOUND);
        }
        return resultMapper.selectByRunId(runId);
    }

    private void publishCandidate(LearningEvaluationRun run, OffsetDateTime now) {
        Knowledge knowledge = requireKnowledge(run.getKnowledgeId());
        KnowledgeVersion target = requireVersion(run.getVersionId());
        if (!Integer.valueOf(KnowledgeCodes.VERSION_WAITING_EVALUATION)
                .equals(target.getVersionStatus())) {
            throw new BusinessException(BusinessErrorCode.STATE_CONFLICT);
        }
        if (knowledge.getCurrentVersionId() != null
                && !knowledge.getCurrentVersionId().equals(target.getId())) {
            KnowledgeVersion old = requireVersion(knowledge.getCurrentVersionId());
            old.setVersionStatus(KnowledgeCodes.VERSION_ARCHIVED);
            old.setUpdatedBy(SYSTEM_OPERATOR);
            versionMapper.updateById(old);
        }
        target.setVersionStatus(KnowledgeCodes.VERSION_PUBLISHED);
        target.setPublishedAt(now);
        target.setUpdatedBy(SYSTEM_OPERATOR);
        versionMapper.updateById(target);
        knowledge.setCurrentVersionId(target.getId());
        knowledge.setPendingVersionId(null);
        knowledge.setStatus(KnowledgeCodes.KNOWLEDGE_ACTIVE);
        knowledge.setUpdatedBy(SYSTEM_OPERATOR);
        knowledgeMapper.updateById(knowledge);
        caseMapper.activateByVersion(target.getId(), SYSTEM_OPERATOR, now);
        createOutbox(knowledge, target, now);
    }

    private void rejectCandidate(LearningEvaluationRun run, OffsetDateTime now) {
        Knowledge knowledge = requireKnowledge(run.getKnowledgeId());
        KnowledgeVersion target = requireVersion(run.getVersionId());
        target.setVersionStatus(KnowledgeCodes.VERSION_REJECTED);
        target.setUpdatedBy(SYSTEM_OPERATOR);
        versionMapper.updateById(target);
        knowledge.setPendingVersionId(null);
        knowledge.setUpdatedBy(SYSTEM_OPERATOR);
        knowledgeMapper.updateById(knowledge);
        caseMapper.rejectByVersion(target.getId(), SYSTEM_OPERATOR, now);
        problemMapper.restoreApprovedByVersion(target.getId(), SYSTEM_OPERATOR);
    }

    private void createOutbox(Knowledge knowledge, KnowledgeVersion version, OffsetDateTime now) {
        KnowledgeOutboxEvent event = new KnowledgeOutboxEvent();
        event.setEventId(UUID.randomUUID().toString());
        event.setKnowledgeId(knowledge.getId());
        event.setVersionId(version.getId());
        event.setEventType(KnowledgeCodes.EVENT_UPSERT);
        event.setPayload(toJson(Map.of("knowledgeCode", knowledge.getKnowledgeCode())));
        event.setStatus(KnowledgeCodes.OUTBOX_PENDING);
        event.setRetryCount(0);
        event.setNextRetryAt(version.getEffectiveAt().isAfter(now) ? version.getEffectiveAt() : now);
        outboxMapper.insert(event);
    }

    private void copyMetrics(LearningEvaluationRun run, ReleaseEvaluationResult result) {
        run.setTotalCases(result.totalCases());
        run.setRecallAt1(result.recallAt1());
        run.setRecallAt3(result.recallAt3());
        run.setThresholdRecall(result.thresholdRecall());
        run.setPositiveCases(result.positiveCases());
        run.setHardNegativeCases(result.hardNegativeCases());
        run.setHardNegativeFalsePositiveRate(result.hardNegativeFalsePositiveRate());
        run.setErrorCount(result.errorCount());
        run.setAverageLatencyMs(result.averageLatencyMs());
        run.setP95LatencyMs(result.p95LatencyMs());
        run.setDistanceThreshold(result.distanceThreshold());
    }

    private LearningEvaluationRun lockProcessing(long id) {
        LearningEvaluationRun run = runMapper.selectOne(
                Wrappers.<LearningEvaluationRun>lambdaQuery()
                        .eq(LearningEvaluationRun::getId, id)
                        .last("FOR UPDATE"));
        if (run == null || !Integer.valueOf(LearningProblemCodes.EVALUATION_PROCESSING)
                .equals(run.getStatus())) {
            throw new BusinessException(BusinessErrorCode.STATE_CONFLICT);
        }
        return run;
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

    private String toJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("自动验收结果序列化失败", exception);
        }
    }
}
