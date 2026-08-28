package com.smartcustomerservice.business.order.domain;

import lombok.Getter;
import lombok.RequiredArgsConstructor;

/**
 * 订单状态由 Java 业务服务统一定义。
 *
 * <p>数据库保存枚举名称，例如 SHIPPED；displayName 是返回给用户的中文名称。</p>
 */
@Getter
@RequiredArgsConstructor
public enum OrderStatus {
    CREATED("待付款"),
    PAID("已付款"),
    PROCESSING("备货中"),
    SHIPPED("已发货"),
    DELIVERED("已签收"),
    CANCELLED("已取消"),
    REFUNDING("退款处理中"),
    REFUNDED("已退款"),
    CLOSED("已关闭");

    private final String displayName;
}
