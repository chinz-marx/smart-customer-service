package com.smartcustomerservice.business.common.api;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.http.converter.json.Jackson2ObjectMapperBuilder;

import static org.assertj.core.api.Assertions.assertThat;

/** 验证统一响应中的 Java 时间类型能够被 Spring MVC 正常输出为 JSON。 */
class ToolResponseSerializationTest {

    @Test
    void shouldSerializeInstantTimestamp() throws Exception {
        // 使用与 Spring MVC 相同的 Builder，让测试覆盖实际 HTTP 序列化模块发现逻辑。
        ObjectMapper objectMapper = Jackson2ObjectMapperBuilder.json().build();
        ToolResponse<String> response = ToolResponse.success(
                "TEST_OK",
                "操作成功",
                "request-test-001",
                "payload"
        );

        String json = objectMapper.writeValueAsString(response);

        assertThat(json).contains("\"timestamp\"");
        assertThat(json).contains("\"code\":\"TEST_OK\"");
    }
}
