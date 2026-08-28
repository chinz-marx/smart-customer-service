package com.smartcustomerservice.business.common.api;

import lombok.Builder;
import lombok.Value;

import java.time.Instant;

/**
 * Java Tool API 的统一响应结构。
 *
 * <p>Python 端只需要判断 success/code，再读取 data，不必为每个业务 Tool
 * 编写一套不同的解析逻辑。</p>
 */
@Value
@Builder
public class ToolResponse<T> {
    boolean success;
    String code;
    String message;
    String requestId;
    Instant timestamp;
    T data;

    /** 创建一次正常的业务响应；“未查到订单”也属于正常查询结果。 */
    public static <T> ToolResponse<T> success(
            String code, String message, String requestId, T data) {
        return ToolResponse.<T>builder()
                .success(true)
                .code(code)
                .message(message)
                .requestId(requestId)
                .timestamp(Instant.now())
                .data(data)
                .build();
    }

    /** 创建参数错误、鉴权失败、系统异常等失败响应。 */
    public static <T> ToolResponse<T> failure(
            String code, String message, String requestId) {
        return ToolResponse.<T>builder()
                .success(false)
                .code(code)
                .message(message)
                .requestId(requestId)
                .timestamp(Instant.now())
                .build();
    }
}
