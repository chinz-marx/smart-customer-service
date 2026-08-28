package com.smartcustomerservice.business.knowledge.domain;

import com.baomidou.mybatisplus.annotation.FieldStrategy;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.OffsetDateTime;

/** 知识主表只保存稳定身份、分类和当前/待审批版本指针。 */
@Data
@TableName(value = "kb_knowledge", schema = "business")
public class Knowledge {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String knowledgeCode;
    private Long categoryId;
    private Long currentVersionId;

    /**
     * 审批结束必须把字段更新为NULL；ALWAYS覆盖MyBatis-Plus默认的非空更新策略。
     */
    @TableField(updateStrategy = FieldStrategy.ALWAYS)
    private Long pendingVersionId;

    private Integer status;
    private String createdBy;
    private String updatedBy;
    private OffsetDateTime createdAt;
    private OffsetDateTime updatedAt;
    private Integer lockVersion;
}
