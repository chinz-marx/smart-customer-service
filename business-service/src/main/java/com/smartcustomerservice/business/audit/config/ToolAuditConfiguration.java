package com.smartcustomerservice.business.audit.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.DependsOn;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

import java.util.concurrent.ThreadPoolExecutor;

@Configuration(proxyBeanMethods = false)
public class ToolAuditConfiguration {

    @Bean
    @DependsOn("dataSource") // 停机时先排空审计队列，再关闭数据库连接池。
    public ThreadPoolTaskExecutor toolAuditExecutor(
            @Value("${tool.audit.threads:2}") int threads,
            @Value("${tool.audit.queue-capacity:1000}") int queueCapacity) {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(threads);
        executor.setMaxPoolSize(threads);
        executor.setQueueCapacity(queueCapacity);
        executor.setThreadNamePrefix("tool-audit-");
        // 队列满时由服务记录失败，不能退回请求线程执行数据库写入。
        executor.setRejectedExecutionHandler(new ThreadPoolExecutor.AbortPolicy());
        executor.setWaitForTasksToCompleteOnShutdown(true);
        executor.setAwaitTerminationSeconds(10);
        return executor;
    }
}
