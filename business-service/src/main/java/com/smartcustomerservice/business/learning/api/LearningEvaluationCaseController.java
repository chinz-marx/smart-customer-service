package com.smartcustomerservice.business.learning.api;

import com.smartcustomerservice.business.common.api.ToolResponse;
import com.smartcustomerservice.business.common.trace.RequestIdFilter;
import com.smartcustomerservice.business.knowledge.api.dto.PageResult;
import com.smartcustomerservice.business.learning.api.dto.EvaluationCaseListItem;
import com.smartcustomerservice.business.learning.service.LearningEvaluationCaseService;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** 评测中心真实测试集查询API。 */
@RestController
@RequestMapping("/api/admin/learning/evaluation-cases")
@RequiredArgsConstructor
public class LearningEvaluationCaseController {
    private final LearningEvaluationCaseService service;

    @GetMapping
    public ToolResponse<PageResult<EvaluationCaseListItem>> list(
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) Integer status,
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "50") long size,
            HttpServletRequest request) {
        Object requestId = request.getAttribute(RequestIdFilter.ATTRIBUTE_NAME);
        return ToolResponse.success(
                "LEARNING_EVALUATION_CASE_LIST_OK", "操作成功",
                requestId == null ? "unknown" : requestId.toString(),
                service.list(keyword, status, page, size));
    }
}
