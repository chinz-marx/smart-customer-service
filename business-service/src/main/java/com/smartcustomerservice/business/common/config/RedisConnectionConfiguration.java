package com.smartcustomerservice.business.common.config;

import io.lettuce.core.ClientOptions;
import io.lettuce.core.SocketOptions;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.data.redis.LettuceClientConfigurationBuilderCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.time.Duration;

/** Redis长连接配置，避免连接被防火墙或NAT静默回收后首个命令等待超时。 */
@Configuration(proxyBeanMethods = false)
public class RedisConnectionConfiguration {

    @Bean
    LettuceClientConfigurationBuilderCustomizer redisTcpKeepAliveCustomizer(
            @Value("${business.redis.tcp-keepalive.enabled:true}") boolean enabled,
            @Value("${business.redis.tcp-keepalive.idle:30s}") Duration idle,
            @Value("${business.redis.tcp-keepalive.interval:10s}") Duration interval,
            @Value("${business.redis.tcp-keepalive.count:3}") int count) {
        SocketOptions.KeepAliveOptions keepAliveOptions =
                SocketOptions.KeepAliveOptions.builder()
                        .enable(enabled)
                        .idle(idle)
                        .interval(interval)
                        .count(count)
                        .build();
        SocketOptions socketOptions = SocketOptions.builder()
                .keepAlive(keepAliveOptions)
                .build();

        return builder -> builder.clientOptions(
                ClientOptions.builder()
                        .socketOptions(socketOptions)
                        .build());
    }
}
