package com.smartcustomerservice.business.customer.domain;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDate;
import java.time.OffsetDateTime;

/** 用户当前会员等级和已生效权益摘要。 */
@Data
@TableName(value = "customer_member_profile", schema = "business")
public class CustomerMemberProfile {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String userId;
    private String levelCode;
    private String levelName;
    private Integer growthValue;
    private String benefitsText;
    private LocalDate validUntil;
    private OffsetDateTime updatedAt;
    @TableLogic(value = "false", delval = "true")
    private Boolean deleted;
}
