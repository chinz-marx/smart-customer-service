package com.smartcustomerservice.business.knowledge.domain;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.OffsetDateTime;

/** Python 返回的切片元数据；向量本身只保存在 Redis Search。 */
@Data
@TableName(value = "kb_knowledge_chunk", schema = "business")
public class KnowledgeChunk {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long knowledgeId;
    private Long versionId;
    private Integer chunkNo;
    private String chunkContent;
    private String contentHash;
    private String redisKey;
    private Integer indexVersion;
    private Integer syncStatus;
    private String syncError;
    private OffsetDateTime syncedAt;
    private OffsetDateTime createdAt;
    private OffsetDateTime updatedAt;
}
