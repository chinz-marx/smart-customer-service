package com.smartcustomerservice.business.common.error;

import com.smartcustomerservice.business.common.api.ToolResponse;
import com.smartcustomerservice.business.common.trace.RequestIdFilter;
import jakarta.servlet.http.HttpServletRequest;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.collections4.CollectionUtils;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.List;

/** 把所有异常转换成固定 JSON，避免把 Java 堆栈或数据库细节暴露给 Python。 */
@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(BusinessException.class)
    public ResponseEntity<ToolResponse<Void>> handleBusinessException(
            BusinessException exception,
            HttpServletRequest request) {
        BusinessErrorCode error = exception.getErrorCode();
        return ResponseEntity.status(error.getHttpStatus())
                .body(ToolResponse.failure(error.getCode(), error.getMessage(), requestId(request)));
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ToolResponse<Void>> handleValidationException(
            MethodArgumentNotValidException exception,
            HttpServletRequest request) {
        List<FieldError> errors = exception.getBindingResult().getFieldErrors();
        String message = CollectionUtils.isNotEmpty(errors)
                ? errors.getFirst().getDefaultMessage()
                : BusinessErrorCode.INVALID_ARGUMENT.getMessage();
        return ResponseEntity.badRequest().body(ToolResponse.failure(
                BusinessErrorCode.INVALID_ARGUMENT.getCode(), message, requestId(request)));
    }

    /** JSON 语法错误或字段类型不匹配属于客户端参数错误，不应返回系统 500。 */
    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<ToolResponse<Void>> handleUnreadableMessage(
            HttpMessageNotReadableException exception,
            HttpServletRequest request) {
        BusinessErrorCode error = BusinessErrorCode.INVALID_ARGUMENT;
        return ResponseEntity.badRequest()
                .body(ToolResponse.failure(error.getCode(), error.getMessage(), requestId(request)));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ToolResponse<Void>> handleUnexpectedException(
            Exception exception,
            HttpServletRequest request) {
        // 完整异常只进入服务日志，对外始终返回稳定且不含敏感信息的提示。
        log.error("Unhandled business service exception", exception);
        BusinessErrorCode error = BusinessErrorCode.INTERNAL_ERROR;
        return ResponseEntity.status(error.getHttpStatus())
                .body(ToolResponse.failure(error.getCode(), error.getMessage(), requestId(request)));
    }

    private String requestId(HttpServletRequest request) {
        Object value = request.getAttribute(RequestIdFilter.ATTRIBUTE_NAME);
        return value == null ? "unknown" : value.toString();
    }
}