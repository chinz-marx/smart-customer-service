package com.smartcustomerservice.business.order.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.smartcustomerservice.business.order.api.dto.OrderQueryRequest;
import com.smartcustomerservice.business.order.api.dto.OrderToolResult;
import com.smartcustomerservice.business.order.domain.BusinessOrder;
import com.smartcustomerservice.business.order.domain.OrderQueryPolicy;
import com.smartcustomerservice.business.order.domain.OrderStatus;
import com.smartcustomerservice.business.order.mapper.BusinessOrderMapper;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Locale;

/** 完成订单查询、权限隔离、业务规则校验和客服话术组装。 */
@Service
@RequiredArgsConstructor
public class OrderQueryService {
    private final BusinessOrderMapper orderMapper;
    private final OrderQueryPolicy orderQueryPolicy;

    @Transactional(readOnly = true)
    public OrderToolResult query(OrderQueryRequest request) {
        String orderNo = StringUtils.trim(request.getOrderId()).toUpperCase(Locale.ROOT);
        String userId = StringUtils.trim(request.getUserId());

        /*
         * 必须同时按订单号和登录用户查询。不能先按订单号查出记录再在 Java 中判断，
         * 否则不同错误提示或日志可能泄露“别人的订单确实存在”。
         */
        BusinessOrder order = orderMapper.selectOne(
                Wrappers.<BusinessOrder>lambdaQuery()
                        .eq(BusinessOrder::getOrderNo, orderNo)
                        .eq(BusinessOrder::getUserId, userId));

        if (order == null) {
            return notFound(orderNo);
        }

        orderQueryPolicy.validateReadableOrder(order);
        return found(order);
    }

    private OrderToolResult notFound(String orderNo) {
        return OrderToolResult.builder()
                .found(false)
                .orderId(orderNo)
                .answer("没有查询到订单 " + orderNo
                        + "。请核对订单号是否完整；如果订单号确认无误，请联系人工客服进一步核查。")
                .build();
    }

    private OrderToolResult found(BusinessOrder order) {
        OrderStatus status = order.getStatus();
        String progressLine = StringUtils.isBlank(order.getExpectedProgress())
                ? ""
                : "\n进度预估：" + order.getExpectedProgress();
        String logistics = StringUtils.defaultIfBlank(order.getLogisticsText(), "暂无物流信息");
        String answer = "您好，已查询到订单 " + order.getOrderNo() + "：\n"
                + "订单状态：" + status.getDisplayName() + "\n"
                + "物流信息：" + logistics
                + progressLine
                + "\n订单状态以业务系统最新记录为准。";

        return OrderToolResult.builder()
                .found(true)
                .orderId(order.getOrderNo())
                .statusCode(status.name())
                .statusText(status.getDisplayName())
                .logisticsText(logistics)
                .expectedProgress(order.getExpectedProgress())
                .updatedAt(order.getUpdatedAt())
                .answer(answer)
                .build();
    }
}
