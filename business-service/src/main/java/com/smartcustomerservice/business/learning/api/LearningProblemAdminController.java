package com.smartcustomerservice.business.learning.api;

import com.smartcustomerservice.business.common.api.ToolResponse;
import com.smartcustomerservice.business.common.error.BusinessErrorCode;
import com.smartcustomerservice.business.common.error.BusinessException;
import com.smartcustomerservice.business.common.trace.RequestIdFilter;
import com.smartcustomerservice.business.knowledge.api.dto.PageResult;
import com.smartcustomerservice.business.learning.api.dto.ProblemDecisionRequest;
import com.smartcustomerservice.business.learning.api.dto.LearningConversionRequest;
import com.smartcustomerservice.business.learning.api.dto.LearningConversionResult;
import com.smartcustomerservice.business.learning.api.dto.ProblemDetail;
import com.smartcustomerservice.business.learning.api.dto.ProblemListItem;
import com.smartcustomerservice.business.learning.api.dto.StandardAnswerRequest;
import com.smartcustomerservice.business.learning.service.LearningProblemAdminService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** 问题收集与人工审核后台API。 */
@RestController
@RequestMapping("/api/admin/learning/problems")
@RequiredArgsConstructor
public class LearningProblemAdminController {
    private final LearningProblemAdminService service;

    @GetMapping
    public ToolResponse<PageResult<ProblemListItem>> list(
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) Integer status,
            @RequestParam(required = false) Integer sourceType,
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "50") long size,
            HttpServletRequest request) {
        return success("LEARNING_PROBLEM_LIST_OK",
                service.list(keyword, status, sourceType, page, size), request);
    }

    @GetMapping("/{id}")
    public ToolResponse<ProblemDetail> detail(
            @PathVariable long id, HttpServletRequest request) {
        return success("LEARNING_PROBLEM_DETAIL_OK", service.detail(id), request);
    }

    @PutMapping("/{id}/standard-answer")
    public ToolResponse<ProblemDetail> saveStandardAnswer(
            @PathVariable long id,
            @RequestHeader("X-Operator-Id") String operatorId,
            @Valid @RequestBody StandardAnswerRequest body,
            HttpServletRequest request) {
        return success("LEARNING_ANSWER_SAVED",
                service.saveStandardAnswer(id, body, requireOperator(operatorId)), request);
    }

    @PostMapping("/{id}/submit-review")
    public ToolResponse<ProblemDetail> submitForReview(
            @PathVariable long id,
            @RequestHeader("X-Operator-Id") String operatorId,
            HttpServletRequest request) {
        return success("LEARNING_PROBLEM_SUBMITTED",
                service.submitForReview(id, requireOperator(operatorId)), request);
    }

    @PostMapping("/{id}/approve")
    public ToolResponse<ProblemDetail> approve(
            @PathVariable long id,
            @RequestHeader("X-Operator-Id") String operatorId,
            @Valid @RequestBody ProblemDecisionRequest body,
            HttpServletRequest request) {
        return success("LEARNING_PROBLEM_APPROVED",
                service.approve(id, body, requireOperator(operatorId)), request);
    }

    @PostMapping("/{id}/reject")
    public ToolResponse<ProblemDetail> reject(
            @PathVariable long id,
            @RequestHeader("X-Operator-Id") String operatorId,
            @Valid @RequestBody ProblemDecisionRequest body,
            HttpServletRequest request) {
        return success("LEARNING_PROBLEM_REJECTED",
                service.reject(id, body, requireOperator(operatorId)), request);
    }

    @PostMapping("/{id}/ignore")
    public ToolResponse<ProblemDetail> ignore(
            @PathVariable long id,
            @RequestHeader("X-Operator-Id") String operatorId,
            @Valid @RequestBody ProblemDecisionRequest body,
            HttpServletRequest request) {
        return success("LEARNING_PROBLEM_IGNORED",
                service.ignore(id, body, requireOperator(operatorId)), request);
    }

    @PostMapping("/{id}/convert-to-knowledge")
    public ToolResponse<LearningConversionResult> convertToKnowledge(
            @PathVariable long id,
            @RequestHeader("X-Operator-Id") String operatorId,
            @Valid @RequestBody LearningConversionRequest body,
            HttpServletRequest request) {
        return success("LEARNING_PROBLEM_CONVERTED",
                service.convertToKnowledge(id, body, requireOperator(operatorId)), request);
    }

    private String requireOperator(String value) {
        String operator = StringUtils.trimToNull(value);
        if (operator == null || operator.length() > 64) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }
        return operator;
    }

    private <T> ToolResponse<T> success(String code, T data, HttpServletRequest request) {
        Object requestId = request.getAttribute(RequestIdFilter.ATTRIBUTE_NAME);
        return ToolResponse.success(code, "操作成功",
                requestId == null ? "unknown" : requestId.toString(), data);
    }
}
