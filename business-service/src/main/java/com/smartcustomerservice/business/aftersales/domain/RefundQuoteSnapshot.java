package com.smartcustomerservice.business.aftersales.domain;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/** 退款报价快照实体，锁定试算参数、金额、允许的售后方式和有效期。 */
@Data
@TableName(value = "refund_quote_snapshot", schema = "business")
public class RefundQuoteSnapshot {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String quoteToken;
    private String userId;
    private String orderNo;
    private String reasonCode;
    private Boolean received;
    private String refundItemsJson;
    private String availableMethodsJson;
    private BigDecimal refundAmount;
    private BigDecimal goodsAmount;
    private BigDecimal discountDeduction;
    private BigDecimal pointsDeduction;
    private BigDecimal shippingRefund;
    private String status;
    private OffsetDateTime expiresAt;
    private OffsetDateTime usedAt;
    private OffsetDateTime createdAt;
    private OffsetDateTime updatedAt;
    @TableLogic(value = "false", delval = "true")
    private Boolean deleted;
}
