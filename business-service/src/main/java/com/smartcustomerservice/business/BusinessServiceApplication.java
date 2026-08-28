package com.smartcustomerservice.business;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Java 业务服务启动入口。
 *
 * <p>本服务只负责真实业务规则、数据库访问和提供 Tool API，不做意图识别、
 * 槽位抽取、置信度计算或大模型回答，这些能力继续由 Python 编排层负责。</p>
 */
@SpringBootApplication
@MapperScan({
        "com.smartcustomerservice.business.order.mapper",
        "com.smartcustomerservice.business.audit.mapper",
        "com.smartcustomerservice.business.customer.mapper",
        "com.smartcustomerservice.business.aftersales.mapper"
})
public class BusinessServiceApplication {

    public static void main(String[] args) {
        SpringApplication.run(BusinessServiceApplication.class, args);
    }
}
