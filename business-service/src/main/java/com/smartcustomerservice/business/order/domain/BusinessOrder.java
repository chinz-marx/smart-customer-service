package com.smartcustomerservice.business.order.domain;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.OffsetDateTime;

/** business.business_order 表对应的 MyBatis-Plus 实体。 */
@Getter
@Setter
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "business_order", schema = "business")
public class BusinessOrder {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String orderNo;
    private String userId;
    private OrderStatus status;
    private String logisticsText;
    private String expectedProgress;
    private Long version;
    private OffsetDateTime createdAt;
    private OffsetDateTime updatedAt;

    /**
     * 逻辑删除标记。调用 BaseMapper 普通查询时，MyBatis-Plus 会自动补充 deleted=false。
     */
    @TableLogic(value = "false", delval = "true")
    private Boolean deleted;
}
