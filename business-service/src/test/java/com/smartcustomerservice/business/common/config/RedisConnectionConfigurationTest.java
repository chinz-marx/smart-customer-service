package com.smartcustomerservice.business.common.config;

import io.lettuce.core.ClientOptions;
import io.lettuce.core.SocketOptions;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.connection.lettuce.LettuceClientConfiguration;

import java.time.Duration;

import static org.assertj.core.api.Assertions.assertThat;

class RedisConnectionConfigurationTest {

    @Test
    void shouldEnableTcpKeepAliveWithConfiguredProbeIntervals() {
        RedisConnectionConfiguration configuration = new RedisConnectionConfiguration();
        var customizer = configuration.redisTcpKeepAliveCustomizer(
                true, Duration.ofSeconds(30), Duration.ofSeconds(10), 3);
        var builder = LettuceClientConfiguration.builder();

        customizer.customize(builder);

        ClientOptions clientOptions = builder.build().getClientOptions().orElseThrow();
        SocketOptions socketOptions = clientOptions.getSocketOptions();
        assertThat(socketOptions.isKeepAlive()).isTrue();
        assertThat(socketOptions.getKeepAlive().isEnabled()).isTrue();
        assertThat(socketOptions.getKeepAlive().getIdle()).isEqualTo(Duration.ofSeconds(30));
        assertThat(socketOptions.getKeepAlive().getInterval()).isEqualTo(Duration.ofSeconds(10));
        assertThat(socketOptions.getKeepAlive().getCount()).isEqualTo(3);
    }
}
