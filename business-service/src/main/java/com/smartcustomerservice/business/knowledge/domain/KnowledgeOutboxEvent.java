package com.smartcustomerservice.business.knowledge.domain;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.smartcustomerservice.business.knowledge.persistence.JsonbStringTypeHandler;
import lombok.Data;
import org.apache.ibatis.type.JdbcType;

import java.time.OffsetDateTime;

/** 审批事务与 Redis 发布之间的可靠消息，失败后按退避时间重试。 */
@Data
@TableName(value = "kb_outbox_event", schema = "business", autoResultMap = true)
public class KnowledgeOutboxEvent {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String eventId;
    private Long knowledgeId;
    private Long versionId;
    private Integer eventType;
    @TableField(typeHandler = JsonbStringTypeHandler.class, jdbcType = JdbcType.OTHER)
    private String payload;
    private Integer status;
    private Integer retryCount;
    private OffsetDateTime nextRetryAt;
    private String lastError;
    private OffsetDateTime createdAt;
    private OffsetDateTime processedAt;
}
