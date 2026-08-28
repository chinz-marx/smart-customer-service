package com.smartcustomerservice.business.aftersales.domain;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/** 异步支付退款任务；afterSalesNo同时作为支付侧幂等业务号。 */
@Data
@TableName(value = "payment_refund_task", schema = "business")
public class PaymentRefundTask {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String taskNo;
    private String afterSalesNo;
    private BigDecimal refundAmount;
    private String status;
    private Integer attempts;
    private OffsetDateTime nextRetryAt;
    private String paymentTransactionNo;
    private String lastError;
    private OffsetDateTime createdAt;
    private OffsetDateTime updatedAt;
    private OffsetDateTime processedAt;
}
