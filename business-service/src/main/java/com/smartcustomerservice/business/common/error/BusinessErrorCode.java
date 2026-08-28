package com.smartcustomerservice.business.common.error;

import lombok.Getter;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;

/** 集中定义对外错误码，避免不同 Controller 随意拼接字符串。 */
@Getter
@RequiredArgsConstructor
public enum BusinessErrorCode {
    INVALID_ARGUMENT("INVALID_ARGUMENT", "请求参数不正确", HttpStatus.BAD_REQUEST),
    RESOURCE_NOT_FOUND("RESOURCE_NOT_FOUND", "请求的数据不存在", HttpStatus.NOT_FOUND),
    STATE_CONFLICT("STATE_CONFLICT", "当前数据状态不允许执行该操作", HttpStatus.CONFLICT),
    LEARNING_PROBLEM_CONTENT_INCOMPLETE(
            "LEARNING_PROBLEM_CONTENT_INCOMPLETE", "问题摘要或代表问法不完整，暂不能提交审核", HttpStatus.CONFLICT),
    LEARNING_PROBLEM_SAMPLE_REQUIRED(
            "LEARNING_PROBLEM_SAMPLE_REQUIRED", "问题缺少真实用户样本，暂不能提交审核", HttpStatus.CONFLICT),
    OPERATION_FORBIDDEN("OPERATION_FORBIDDEN", "当前操作不被允许", HttpStatus.FORBIDDEN),
    UNAUTHORIZED_TOOL_CALL("UNAUTHORIZED_TOOL_CALL", "Tool 调用身份校验失败", HttpStatus.UNAUTHORIZED),
    ORDER_DATA_INVALID("ORDER_DATA_INVALID", "订单数据状态异常", HttpStatus.INTERNAL_SERVER_ERROR),
    INTERNAL_ERROR("INTERNAL_ERROR", "业务服务暂时不可用", HttpStatus.INTERNAL_SERVER_ERROR);

    private final String code;
    private final String message;
    private final HttpStatus httpStatus;
}
