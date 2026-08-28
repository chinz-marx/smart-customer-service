package com.smartcustomerservice.business.knowledge.domain;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.smartcustomerservice.business.knowledge.persistence.StringArrayTypeHandler;
import lombok.Data;
import org.apache.ibatis.type.JdbcType;

import java.time.OffsetDateTime;

/** 每次新增或修改都会创建新版本，审批前不会覆盖线上内容。 */
@Data
@TableName(value = "kb_knowledge_version", schema = "business", autoResultMap = true)
public class KnowledgeVersion {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long knowledgeId;
    private Integer versionNo;
    private String title;
    private String content;
    @TableField(typeHandler = StringArrayTypeHandler.class, jdbcType = JdbcType.ARRAY)
    private String[] tags;
    private String intentCode;
    private Integer versionStatus;
    private OffsetDateTime effectiveAt;
    private OffsetDateTime expiredAt;
    private OffsetDateTime publishedAt;
    private String createdBy;
    private String updatedBy;
    private OffsetDateTime createdAt;
    private OffsetDateTime updatedAt;
}
