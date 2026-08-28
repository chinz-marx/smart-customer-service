package com.smartcustomerservice.business.common.error;

import lombok.Getter;

/** 可预期的业务异常，由统一异常处理器转换成 JSON。 */
@Getter
public class BusinessException extends RuntimeException {
    private final BusinessErrorCode errorCode;

    public BusinessException(BusinessErrorCode errorCode) {
        super(errorCode.getMessage());
        this.errorCode = errorCode;
    }
}
