package com.smartcustomerservice.business.common.security;

import com.smartcustomerservice.business.common.error.BusinessErrorCode;
import com.smartcustomerservice.business.common.error.BusinessException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.apache.commons.lang3.StringUtils;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/** 只允许持有内部令牌的 Python 编排服务调用内部 Tool API。 */
@Component
public class InternalTokenInterceptor implements HandlerInterceptor {
    public static final String HEADER_NAME = "X-Internal-Token";
    private final byte[] expectedToken;

    public InternalTokenInterceptor(
            @Value("${tool.security.internal-token}") String expectedToken) {
        if (StringUtils.isBlank(expectedToken)) {
            throw new IllegalStateException("tool.security.internal-token 不能为空");
        }
        this.expectedToken = expectedToken.getBytes(StandardCharsets.UTF_8);
    }

    @Override
    public boolean preHandle(
            HttpServletRequest request,
            HttpServletResponse response,
            Object handler) {
        String actual = StringUtils.defaultString(request.getHeader(HEADER_NAME));
        // 使用恒定时间比较，降低根据响应耗时猜测令牌内容的风险。
        boolean matched = MessageDigest.isEqual(
                expectedToken,
                actual.getBytes(StandardCharsets.UTF_8));
        if (!matched) {
            throw new BusinessException(BusinessErrorCode.UNAUTHORIZED_TOOL_CALL);
        }
        return true;
    }
}
