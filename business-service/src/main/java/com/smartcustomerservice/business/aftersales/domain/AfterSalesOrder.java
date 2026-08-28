package com.smartcustomerservice.business.aftersales.domain;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/** 正式售后申请实体，状态和支付任务分离。 */
@Data
@TableName(value = "after_sales_order", schema = "business")
public class AfterSalesOrder {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String afterSalesNo;
    private String quoteToken;
    private String idempotencyKey;
    private String userId;
    private String orderNo;
    private String method;
    private String reasonCode;
    private String status;
    private String riskLevel;
    private Boolean reviewRequired;
    private BigDecimal refundAmount;
    private String refundItemsJson;
    private String paymentTransactionNo;
    private Long reviewedBy;
    private OffsetDateTime reviewedAt;
    private OffsetDateTime createdAt;
    private OffsetDateTime updatedAt;
    @TableLogic(value = "false", delval = "true")
    private Boolean deleted;
}
