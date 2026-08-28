package com.smartcustomerservice.business.knowledge.config;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;

/** 独立开启知识库 Mapper 扫描和 Outbox 定时任务，避免影响现有订单模块。 */
@Configuration
@EnableScheduling
@MapperScan({
        "com.smartcustomerservice.business.knowledge.mapper",
        "com.smartcustomerservice.business.learning.mapper"
})
public class KnowledgeModuleConfiguration {
}
