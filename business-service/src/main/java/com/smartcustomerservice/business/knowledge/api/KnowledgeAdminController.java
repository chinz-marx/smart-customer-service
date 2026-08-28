package com.smartcustomerservice.business.knowledge.api;

import com.smartcustomerservice.business.common.api.ToolResponse;
import com.smartcustomerservice.business.common.error.BusinessErrorCode;
import com.smartcustomerservice.business.common.error.BusinessException;
import com.smartcustomerservice.business.common.trace.RequestIdFilter;
import com.smartcustomerservice.business.knowledge.api.dto.KnowledgeDetail;
import com.smartcustomerservice.business.knowledge.api.dto.KnowledgeListItem;
import com.smartcustomerservice.business.knowledge.api.dto.KnowledgeReindexResult;
import com.smartcustomerservice.business.knowledge.api.dto.KnowledgeSaveRequest;
import com.smartcustomerservice.business.knowledge.api.dto.PageResult;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeCategory;
import com.smartcustomerservice.business.knowledge.service.KnowledgeAdminService;
import com.smartcustomerservice.business.knowledge.service.KnowledgeReindexService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/** 知识管理后台 API；X-Operator-Id 后续由正式登录网关统一注入。 */
@RestController
@RequestMapping("/api/admin/knowledge")
@RequiredArgsConstructor
public class KnowledgeAdminController {
    private final KnowledgeAdminService service;
    private final KnowledgeReindexService reindexService;

    @GetMapping("/categories")
    public ToolResponse<List<KnowledgeCategory>> categories(HttpServletRequest servletRequest) {
        return success("KB_CATEGORIES_OK", service.listCategories(), servletRequest);
    }

    @GetMapping
    public ToolResponse<PageResult<KnowledgeListItem>> list(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size,
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) Long categoryId,
            @RequestParam(defaultValue = "all") String view,
            HttpServletRequest servletRequest) {
        return success("KB_LIST_OK", service.list(page, size, keyword, categoryId, view), servletRequest);
    }

    @GetMapping("/{id}")
    public ToolResponse<KnowledgeDetail> detail(
            @PathVariable long id, HttpServletRequest servletRequest) {
        return success("KB_DETAIL_OK", service.detail(id), servletRequest);
    }

    @PostMapping
    public ToolResponse<KnowledgeDetail> create(
            @RequestHeader("X-Operator-Id") String operatorId,
            @Valid @RequestBody KnowledgeSaveRequest request,
            HttpServletRequest servletRequest) {
        return success("KB_CREATE_SUBMITTED",
                service.create(request, requireOperator(operatorId)), servletRequest);
    }

    @PutMapping("/{id}")
    public ToolResponse<KnowledgeDetail> update(
            @PathVariable long id,
            @RequestHeader("X-Operator-Id") String operatorId,
            @Valid @RequestBody KnowledgeSaveRequest request,
            HttpServletRequest servletRequest) {
        return success("KB_UPDATE_SUBMITTED",
                service.update(id, request, requireOperator(operatorId)), servletRequest);
    }

    /** 保存编辑草稿但不创建审批单，后续仍需通过PUT /{id}显式提交审批。 */
    @PutMapping("/{id}/draft")
    public ToolResponse<KnowledgeDetail> saveDraft(
            @PathVariable long id,
            @RequestHeader("X-Operator-Id") String operatorId,
            @Valid @RequestBody KnowledgeSaveRequest request,
            HttpServletRequest servletRequest) {
        return success("KB_DRAFT_SAVED",
                service.saveDraft(id, request, requireOperator(operatorId)), servletRequest);
    }

    /** DELETE 的业务含义是提交停用审批，不会直接物理删除知识。 */
    @DeleteMapping("/{id}")
    public ToolResponse<KnowledgeDetail> requestDisable(
            @PathVariable long id,
            @RequestHeader("X-Operator-Id") String operatorId,
            HttpServletRequest servletRequest) {
        return success("KB_DISABLE_SUBMITTED",
                service.requestDisable(id, requireOperator(operatorId)), servletRequest);
    }

    /**
     * 将数据库中当前有效的已发布版本重新投递给Python索引发布器。
     * 该操作不修改知识内容和审批状态，可以安全用于Redis索引恢复或全量重建。
     */
    @PostMapping("/reindex")
    public ToolResponse<KnowledgeReindexResult> reindex(
            @RequestHeader("X-Operator-Id") String operatorId,
            HttpServletRequest servletRequest) {
        return success("KB_REINDEX_QUEUED",
                reindexService.reindexPublished(requireOperator(operatorId)), servletRequest);
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
