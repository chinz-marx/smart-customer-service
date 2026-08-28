package com.smartcustomerservice.business.aftersales.domain;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/** 订单商品售后投影，保存购买数量、剩余可退数量和售后期限。 */
@Getter
@Setter
@TableName(value = "order_refund_item", schema = "business")
public class OrderRefundItem {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String orderNo;
    private String skuId;
    private String skuName;
    private BigDecimal unitPrice;
    private Integer purchasedQuantity;
    private Integer refundableQuantity;
    private Boolean returnable;
    private OffsetDateTime afterSaleDeadline;
    private OffsetDateTime updatedAt;

    /** MyBatis-Plus逻辑删除标记，普通查询会自动排除已删除商品。 */
    @TableLogic(value = "false", delval = "true")
    private Boolean deleted;
}
