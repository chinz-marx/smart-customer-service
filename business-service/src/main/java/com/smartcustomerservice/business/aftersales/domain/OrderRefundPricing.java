package com.smartcustomerservice.business.aftersales.domain;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/** 订单成交价格快照，用于按商品成交金额比例分摊优惠和积分抵扣。 */
@Getter
@Setter
@TableName(value = "order_refund_pricing", schema = "business")
public class OrderRefundPricing {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String orderNo;
    private BigDecimal goodsAmount;
    private BigDecimal shippingFee;
    private BigDecimal orderDiscount;
    private BigDecimal couponDiscount;
    private BigDecimal pointsDiscount;
    private OffsetDateTime updatedAt;

    /** MyBatis-Plus逻辑删除标记，普通查询会自动排除已删除快照。 */
    @TableLogic(value = "false", delval = "true")
    private Boolean deleted;
}
