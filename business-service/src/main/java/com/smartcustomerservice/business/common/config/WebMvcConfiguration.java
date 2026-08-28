package com.smartcustomerservice.business.common.config;

import com.smartcustomerservice.business.common.security.InternalTokenInterceptor;
import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/** 注册 Web 层公共规则。健康检查不属于内部 Tool，因此不会被令牌拦截。 */
@Configuration
@RequiredArgsConstructor
public class WebMvcConfiguration implements WebMvcConfigurer {
    private final InternalTokenInterceptor internalTokenInterceptor;

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(internalTokenInterceptor)
                // REST 兼容接口和 MCP Streamable HTTP 入口使用同一内部令牌。
                .addPathPatterns("/api/internal/**", "/mcp", "/mcp/**");
    }
}
