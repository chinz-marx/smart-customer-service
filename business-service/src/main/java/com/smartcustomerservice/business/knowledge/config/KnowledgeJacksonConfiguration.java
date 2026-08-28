package com.smartcustomerservice.business.knowledge.config;

import com.fasterxml.jackson.core.JsonGenerator;
import com.fasterxml.jackson.databind.JsonSerializer;
import com.fasterxml.jackson.databind.SerializerProvider;
import org.springframework.boot.autoconfigure.jackson.Jackson2ObjectMapperBuilderCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.io.IOException;
import java.time.OffsetDateTime;

/** 为知识审计和Outbox定制时间序列化，同时保留Spring Boot的Jackson自动配置。 */
@Configuration
public class KnowledgeJacksonConfiguration {

    /**
     * 只向Spring管理的ObjectMapper增加OffsetDateTime格式，不再自行new ObjectMapper。
     *
     * <p>自行声明ObjectMapper Bean会让Spring Boot停止创建默认实例，进而丢失
     * JavaTimeModule等自动发现模块，导致统一响应中的Instant无法输出JSON。</p>
     */
    @Bean
    public Jackson2ObjectMapperBuilderCustomizer knowledgeTimeCustomizer() {
        return builder -> builder.serializerByType(
                OffsetDateTime.class,
                new OffsetDateTimeSerializer()
        );
    }

    /** 审计快照只需要序列化时间，统一保存为带时区的ISO-8601字符串。 */
    private static final class OffsetDateTimeSerializer extends JsonSerializer<OffsetDateTime> {
        @Override
        public void serialize(
                OffsetDateTime value,
                JsonGenerator generator,
                SerializerProvider serializers) throws IOException {
            generator.writeString(value.toString());
        }
    }
}
