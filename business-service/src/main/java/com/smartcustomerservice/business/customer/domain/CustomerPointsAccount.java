package com.smartcustomerservice.business.customer.domain;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDate;
import java.time.OffsetDateTime;

/** 用户积分账户实体；查询始终使用可信登录用户ID，不接受模型传入其他用户身份。 */
@Data
@TableName(value = "customer_points_account", schema = "business")
public class CustomerPointsAccount {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String userId;
    private Integer pointsBalance;
    private Integer expiringPoints;
    private LocalDate expireDate;
    private OffsetDateTime updatedAt;
    @TableLogic(value = "false", delval = "true")
    private Boolean deleted;
}
