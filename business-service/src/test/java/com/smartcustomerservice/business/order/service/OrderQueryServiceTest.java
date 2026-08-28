package com.smartcustomerservice.business.order.service;

import com.smartcustomerservice.business.common.error.BusinessException;
import com.smartcustomerservice.business.order.api.dto.OrderQueryRequest;
import com.smartcustomerservice.business.order.api.dto.OrderToolResult;
import com.smartcustomerservice.business.order.domain.BusinessOrder;
import com.smartcustomerservice.business.order.domain.OrderQueryPolicy;
import com.smartcustomerservice.business.order.domain.OrderStatus;
import com.smartcustomerservice.business.order.mapper.BusinessOrderMapper;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Proxy;
import java.time.OffsetDateTime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/** 不依赖真实 PostgreSQL 的订单业务单元测试。 */
class OrderQueryServiceTest {

    @Test
    void shouldReturnDirectAnswerWhenOrderExists() {
        BusinessOrder order = BusinessOrder.builder()
                .id(1L)
                .orderNo("ORDER_123456")
                .userId("USER_10001")
                .status(OrderStatus.SHIPPED)
                .logisticsText("包裹已从上海分拨中心发出")
                .expectedProgress("预计明天送达")
                .updatedAt(OffsetDateTime.now())
                .deleted(false)
                .build();

        OrderToolResult result = serviceReturning(order)
                .query(request(" order_123456 ", "USER_10001"));

        assertThat(result.isFound()).isTrue();
        assertThat(result.getStatusCode()).isEqualTo("SHIPPED");
        assertThat(result.getAnswer()).contains("订单状态：已发货", "预计明天送达");
    }

    @Test
    void shouldReturnNormalNotFoundResultWithoutCallingLlm() {
        OrderToolResult result = serviceReturning(null)
                .query(request("ORDER_999999", "USER_10001"));

        assertThat(result.isFound()).isFalse();
        assertThat(result.getAnswer()).contains("没有查询到订单 ORDER_999999", "联系人工客服");
    }

    @Test
    void shouldRejectShippedOrderWithoutLogisticsData() {
        BusinessOrder invalidOrder = BusinessOrder.builder()
                .orderNo("ORDER_123456")
                .userId("USER_10001")
                .status(OrderStatus.SHIPPED)
                .deleted(false)
                .build();

        assertThatThrownBy(() -> serviceReturning(invalidOrder)
                .query(request("ORDER_123456", "USER_10001")))
                .isInstanceOf(BusinessException.class)
                .hasMessage("订单数据状态异常");
    }

    /**
     * 用 JDK 动态代理实现一个最小 Mapper 测试替身，避免单元测试依赖数据库，
     * 同时也不需要 Mockito 在 JDK 运行时加载 agent。
     */
    private OrderQueryService serviceReturning(BusinessOrder result) {
        BusinessOrderMapper mapper = (BusinessOrderMapper) Proxy.newProxyInstance(
                BusinessOrderMapper.class.getClassLoader(),
                new Class<?>[]{BusinessOrderMapper.class},
                (proxy, method, arguments) -> {
                    if ("selectOne".equals(method.getName())) {
                        return result;
                    }
                    throw new UnsupportedOperationException(
                            "本测试没有实现 Mapper 方法: " + method.getName());
                });
        return new OrderQueryService(mapper, new OrderQueryPolicy());
    }

    private OrderQueryRequest request(String orderId, String userId) {
        OrderQueryRequest request = new OrderQueryRequest();
        request.setSessionId("session-test");
        request.setUserId(userId);
        request.setOrderId(orderId);
        return request;
    }
}