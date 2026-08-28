package com.smartcustomerservice.business.order.api;

import com.smartcustomerservice.business.audit.service.ToolAuditService;
import com.smartcustomerservice.business.common.api.ToolResponse;
import com.smartcustomerservice.business.common.error.BusinessException;
import com.smartcustomerservice.business.common.trace.RequestIdFilter;
import com.smartcustomerservice.business.order.api.dto.OrderQueryRequest;
import com.smartcustomerservice.business.order.api.dto.OrderToolResult;
import com.smartcustomerservice.business.order.service.OrderQueryService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.concurrent.TimeUnit;

/** 提供给 Python 编排层调用的订单业务 Tool。 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/internal/tools/orders")
public class OrderToolController {
    private final OrderQueryService orderQueryService;
    private final ToolAuditService toolAuditService;

    @PostMapping("/query")
    public ToolResponse<OrderToolResult> queryOrder(
            @Valid @RequestBody OrderQueryRequest request,
            HttpServletRequest httpRequest) {
        long startedAt = System.nanoTime();
        String requestId = httpRequest.getAttribute(RequestIdFilter.ATTRIBUTE_NAME).toString();

        try {
            OrderToolResult result = orderQueryService.query(request);
            String resultCode = result.isFound() ? "ORDER_FOUND" : "ORDER_NOT_FOUND";
            recordAudit(startedAt, requestId, request, resultCode, true);
            return ToolResponse.success(resultCode, "订单查询完成", requestId, result);
        } catch (BusinessException exception) {
            // 可预期业务失败也必须有审计记录，例如订单数据状态不完整。
            recordAudit(startedAt, requestId, request,
                    exception.getErrorCode().getCode(), false);
            throw exception;
        } catch (RuntimeException exception) {
            recordAudit(startedAt, requestId, request, "INTERNAL_ERROR", false);
            throw exception;
        }
    }

    private void recordAudit(
            long startedAt,
            String requestId,
            OrderQueryRequest request,
            String resultCode,
            boolean success) {
        long durationMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - startedAt);
        toolAuditService.recordOrderQuery(requestId, request, resultCode, success, durationMs);
    }
}