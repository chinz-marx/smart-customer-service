package com.smartcustomerservice.business.knowledge.sync;

import lombok.Data;

/** 已到业务失效时间、等待自动下索引的知识引用。 */
@Data
public class ExpiredKnowledgeItem {
    private Long knowledgeId;
    private String knowledgeCode;
    private Long versionId;
}
