package com.smartcustomerservice.business.common.security;

import com.smartcustomerservice.business.common.error.BusinessException;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/** 验证内部 Tool 令牌不会被缺失或错误请求绕过。 */
class InternalTokenInterceptorTest {

    @Test
    void shouldAcceptCorrectToken() {
        InternalTokenInterceptor interceptor = new InternalTokenInterceptor("test-secret");
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader(InternalTokenInterceptor.HEADER_NAME, "test-secret");

        boolean accepted = interceptor.preHandle(
                request, new MockHttpServletResponse(), new Object());

        assertThat(accepted).isTrue();
    }

    @Test
    void shouldRejectMissingToken() {
        InternalTokenInterceptor interceptor = new InternalTokenInterceptor("test-secret");
        MockHttpServletRequest request = new MockHttpServletRequest();

        assertThatThrownBy(() -> interceptor.preHandle(
                request, new MockHttpServletResponse(), new Object()))
                .isInstanceOf(BusinessException.class)
                .hasMessage("Tool 调用身份校验失败");
    }
}