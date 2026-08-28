package com.smartcustomerservice.business.learning.api;

import com.smartcustomerservice.business.common.api.ToolResponse;
import com.smartcustomerservice.business.common.trace.RequestIdFilter;
import com.smartcustomerservice.business.knowledge.api.dto.PageResult;
import com.smartcustomerservice.business.learning.api.dto.EvaluationRunListItem;
import com.smartcustomerservice.business.learning.api.dto.EvaluationRunCaseResultItem;
import com.smartcustomerservice.business.learning.service.LearningReleaseEvaluationService;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/** 评测中心读取真实自动发布验收批次。 */
@RestController
@RequestMapping("/api/admin/learning/evaluation-runs")
@RequiredArgsConstructor
public class LearningEvaluationRunController {
    private final LearningReleaseEvaluationService service;

    @GetMapping
    public ToolResponse<PageResult<EvaluationRunListItem>> list(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "50") long size,
            HttpServletRequest request) {
        Object requestId = request.getAttribute(RequestIdFilter.ATTRIBUTE_NAME);
        return ToolResponse.success(
                "LEARNING_EVALUATION_RUN_LIST_OK", "操作成功",
                requestId == null ? "unknown" : requestId.toString(),
                service.list(page, size));
    }

    @GetMapping("/{id}/results")
    public ToolResponse<List<EvaluationRunCaseResultItem>> results(
            @PathVariable long id,
            HttpServletRequest request) {
        Object requestId = request.getAttribute(RequestIdFilter.ATTRIBUTE_NAME);
        return ToolResponse.success(
                "LEARNING_EVALUATION_RUN_RESULTS_OK", "操作成功",
                requestId == null ? "unknown" : requestId.toString(),
                service.listResults(id));
    }
}
