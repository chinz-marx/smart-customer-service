package com.smartcustomerservice.business.knowledge.domain;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.smartcustomerservice.business.knowledge.persistence.JsonbStringTypeHandler;
import lombok.Data;
import org.apache.ibatis.type.JdbcType;

import java.time.OffsetDateTime;

/** 管理和审批操作审计，只存用户 ID 与操作前后快照。 */
@Data
@TableName(value = "kb_operation_log", schema = "business", autoResultMap = true)
public class KnowledgeOperationLog {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long knowledgeId;
    private Long versionId;
    private Long approvalId;
    private Integer operationType;
    private String operatorId;
    @TableField(typeHandler = JsonbStringTypeHandler.class, jdbcType = JdbcType.OTHER)
    private String beforeData;
    @TableField(typeHandler = JsonbStringTypeHandler.class, jdbcType = JdbcType.OTHER)
    private String afterData;
    private String requestId;
    private OffsetDateTime createdAt;
}
