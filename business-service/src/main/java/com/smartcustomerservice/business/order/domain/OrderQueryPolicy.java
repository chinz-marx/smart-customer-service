package com.smartcustomerservice.business.order.domain;

import com.smartcustomerservice.business.common.error.BusinessErrorCode;
import com.smartcustomerservice.business.common.error.BusinessException;
import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Component;

import java.util.EnumSet;
import java.util.Set;

/**
 * 订单查询的业务规则集中放在这里，而不是散落在 Controller 或 SQL 中。
 * 后续增加“隐私订单不可展示商品名”等规则时，也继续在策略层扩展。
 */
@Component
public class OrderQueryPolicy {
    private static final Set<OrderStatus> LOGISTICS_REQUIRED_STATUSES =
            EnumSet.of(OrderStatus.SHIPPED, OrderStatus.DELIVERED);

    public void validateReadableOrder(BusinessOrder order) {
        if (order.getStatus() == null) {
            throw new BusinessException(BusinessErrorCode.ORDER_DATA_INVALID);
        }

        // 已发货或已签收却没有物流信息，说明业务数据不完整，不能编造回答给用户。
        if (LOGISTICS_REQUIRED_STATUSES.contains(order.getStatus())
                && StringUtils.isBlank(order.getLogisticsText())) {
            throw new BusinessException(BusinessErrorCode.ORDER_DATA_INVALID);
        }
    }
}
