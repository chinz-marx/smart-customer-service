package com.smartcustomerservice.business.common.trace;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.apache.commons.lang3.StringUtils;
import org.slf4j.MDC;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.UUID;

/** 给每个 HTTP 请求绑定 requestId，方便串联 Python 与 Java 日志。 */
@Component
public class RequestIdFilter extends OncePerRequestFilter {
    public static final String HEADER_NAME = "X-Request-Id";
    public static final String ATTRIBUTE_NAME = "requestId";
    private static final int MAX_REQUEST_ID_LENGTH = 64;

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain) throws ServletException, IOException {
        String requestId = normalizeRequestId(request.getHeader(HEADER_NAME));
        request.setAttribute(ATTRIBUTE_NAME, requestId);
        response.setHeader(HEADER_NAME, requestId);
        MDC.put(ATTRIBUTE_NAME, requestId);
        try {
            filterChain.doFilter(request, response);
        } finally {
            // Web 线程会被线程池复用，必须清理，否则下个请求可能串用旧 requestId。
            MDC.remove(ATTRIBUTE_NAME);
        }
    }

    private String normalizeRequestId(String candidate) {
        String value = StringUtils.trimToEmpty(candidate);
        if (StringUtils.isBlank(value) || value.length() > MAX_REQUEST_ID_LENGTH) {
            return UUID.randomUUID().toString();
        }
        return value;
    }
}
