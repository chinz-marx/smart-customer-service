package com.smartcustomerservice.business.knowledge.domain;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.OffsetDateTime;

/** 原子分片的标准问法；每条问法在Redis Search中拥有独立向量文档。 */
@Data
@TableName(value = "kb_knowledge_question", schema = "business")
public class KnowledgeQuestion {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long knowledgeId;
    private Long versionId;
    private Long chunkId;
    private Integer questionNo;
    private String questionText;
    private String questionHash;
    private String redisKey;
    private Integer syncStatus;
    private String syncError;
    private OffsetDateTime syncedAt;
    private OffsetDateTime createdAt;
    private OffsetDateTime updatedAt;
}
