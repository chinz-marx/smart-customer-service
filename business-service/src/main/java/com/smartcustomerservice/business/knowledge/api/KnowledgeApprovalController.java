package com.smartcustomerservice.business.knowledge.api;

import com.smartcustomerservice.business.common.api.ToolResponse;
import com.smartcustomerservice.business.common.error.BusinessErrorCode;
import com.smartcustomerservice.business.common.error.BusinessException;
import com.smartcustomerservice.business.common.trace.RequestIdFilter;
import com.smartcustomerservice.business.knowledge.api.dto.ApprovalDecisionRequest;
import com.smartcustomerservice.business.knowledge.api.dto.ApprovalListItem;
import com.smartcustomerservice.business.knowledge.api.dto.PageResult;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeApproval;
import com.smartcustomerservice.business.knowledge.service.KnowledgeApprovalService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** 审批中心 API。 */
@RestController
@RequestMapping("/api/admin/knowledge/approvals")
@RequiredArgsConstructor
public class KnowledgeApprovalController {
    private final KnowledgeApprovalService service;

    @GetMapping
    public ToolResponse<PageResult<ApprovalListItem>> list(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size,
            HttpServletRequest request) {
        return success("KB_APPROVAL_LIST_OK", service.listPending(page, size), request);
    }

    @PostMapping("/{id}/approve")
    public ToolResponse<KnowledgeApproval> approve(
            @PathVariable long id,
            @RequestHeader("X-Operator-Id") String operatorId,
            @Valid @RequestBody ApprovalDecisionRequest body,
            HttpServletRequest request) {
        String requestId = requestId(request);
        return ToolResponse.success("KB_APPROVAL_APPROVED", "审批已通过", requestId,
                service.approve(id, body, requireOperator(operatorId), requestId));
    }

    @PostMapping("/{id}/reject")
    public ToolResponse<KnowledgeApproval> reject(
            @PathVariable long id,
            @RequestHeader("X-Operator-Id") String operatorId,
            @Valid @RequestBody ApprovalDecisionRequest body,
            HttpServletRequest request) {
        String requestId = requestId(request);
        return ToolResponse.success("KB_APPROVAL_REJECTED", "审批已驳回", requestId,
                service.reject(id, body, requireOperator(operatorId), requestId));
    }

    @PostMapping("/{id}/cancel")
    public ToolResponse<KnowledgeApproval> cancel(
            @PathVariable long id,
            @RequestHeader("X-Operator-Id") String operatorId,
            HttpServletRequest request) {
        String requestId = requestId(request);
        return ToolResponse.success("KB_APPROVAL_CANCELED", "审批申请已撤销", requestId,
                service.cancel(id, requireOperator(operatorId), requestId));
    }

    private String requireOperator(String value) {
        String operator = StringUtils.trimToNull(value);
        if (operator == null || operator.length() > 64) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }
        return operator;
    }

    private <T> ToolResponse<T> success(String code, T data, HttpServletRequest request) {
        return ToolResponse.success(code, "操作成功", requestId(request), data);
    }

    private String requestId(HttpServletRequest request) {
        Object value = request.getAttribute(RequestIdFilter.ATTRIBUTE_NAME);
        return value == null ? "unknown" : value.toString();
    }
}
