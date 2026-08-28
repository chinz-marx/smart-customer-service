package com.smartcustomerservice.business.learning.sync;

import com.smartcustomerservice.business.knowledge.domain.Knowledge;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeVersion;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeVersionMapper;
import com.smartcustomerservice.business.knowledge.sync.KnowledgePublishPayload;
import com.smartcustomerservice.business.knowledge.sync.KnowledgePublishPayloadFactory;
import com.smartcustomerservice.business.knowledge.sync.PythonKnowledgeSyncClient;
import com.smartcustomerservice.business.learning.domain.LearningEvaluationRun;
import com.smartcustomerservice.business.learning.mapper.LearningEvaluationCaseMapper;
import com.smartcustomerservice.business.learning.service.LearningReleaseEvaluationService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * 正式发布验收执行器。
 *
 * <p>每个 Java 实例都可以扫描任务，数据库原子认领负责防止重复执行。Python 只负责
 * Embedding 和 Redis Search 实测，最终发布状态仍由 Java 的数据库事务决定。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class LearningReleaseEvaluationWorker {
    private final LearningReleaseEvaluationService evaluationService;
    private final LearningEvaluationCaseMapper caseMapper;
    private final KnowledgeMapper knowledgeMapper;
    private final KnowledgeVersionMapper versionMapper;
    private final KnowledgePublishPayloadFactory payloadFactory;
    private final PythonKnowledgeSyncClient pythonClient;

    @Value("${learning.evaluation.max-retries:3}")
    private int maxRetries;

    @Scheduled(
            fixedDelayString = "${learning.evaluation.interval-ms:5000}",
            initialDelayString = "${learning.evaluation.initial-delay-ms:5000}")
    public void evaluateReadyVersions() {
        for (LearningEvaluationRun run : evaluationService.findReady(10)) {
            if (!evaluationService.claim(run)) {
                continue;
            }
            try {
                ReleaseEvaluationPayload payload = buildPayload(run);
                ReleaseEvaluationResult result = pythonClient.evaluate(payload);
                evaluationService.complete(run.getId(), result);
                log.info("知识自动发布验收完成: runNo={}, passed={}",
                        run.getRunNo(), result.passed());
            } catch (Exception exception) {
                log.warn("知识自动发布验收系统调用失败: runNo={}, retry={}",
                        run.getRunNo(), run.getRetryCount() + 1, exception);
                evaluationService.failSystem(run.getId(), exception, maxRetries);
            }
        }
    }

    private ReleaseEvaluationPayload buildPayload(LearningEvaluationRun run) {
        Knowledge knowledge = required(
                knowledgeMapper.selectById(run.getKnowledgeId()), "知识");
        KnowledgeVersion version = required(
                versionMapper.selectById(run.getVersionId()), "知识版本");
        KnowledgePublishPayload knowledgePayload = payloadFactory.build(knowledge, version);
        List<ReleaseEvaluationPayload.CasePayload> cases =
                caseMapper.selectForEvaluation(run.getVersionId()).stream()
                        .map(item -> new ReleaseEvaluationPayload.CasePayload(
                                item.id(), item.questionText(), item.expectedIntent(),
                                item.expectedMatch()))
                        .toList();
        if (cases.size() != run.getTotalCases()) {
            throw new IllegalStateException("待验收用例数量与验收批次不一致");
        }
        return new ReleaseEvaluationPayload(run.getId(), knowledgePayload, cases);
    }

    private <T> T required(T value, String name) {
        if (value == null) {
            throw new IllegalStateException(name + "不存在，无法执行发布验收");
        }
        return value;
    }
}
