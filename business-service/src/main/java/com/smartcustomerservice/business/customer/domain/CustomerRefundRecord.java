package com.smartcustomerservice.business.customer.domain;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/** 用户订单退款记录实体。 */
@Data
@TableName(value = "customer_refund_record", schema = "business")
public class CustomerRefundRecord {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String refundNo;
    private String orderNo;
    private String userId;
    private String status;
    private BigDecimal refundAmount;
    private OffsetDateTime expectedAt;
    private OffsetDateTime updatedAt;
    @TableLogic(value = "false", delval = "true")
    private Boolean deleted;
}
