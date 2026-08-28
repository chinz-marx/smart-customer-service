package com.smartcustomerservice.business.customer.domain;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.OffsetDateTime;

/** 用户活动奖励记录实体。 */
@Data
@TableName(value = "customer_reward_record", schema = "business")
public class CustomerRewardRecord {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String rewardNo;
    private String userId;
    private String activityName;
    private String status;
    private OffsetDateTime expectedAt;
    private OffsetDateTime issuedAt;
    private OffsetDateTime updatedAt;
    @TableLogic(value = "false", delval = "true")
    private Boolean deleted;
}
