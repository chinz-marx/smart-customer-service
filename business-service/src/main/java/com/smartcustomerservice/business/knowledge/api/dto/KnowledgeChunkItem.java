package com.smartcustomerservice.business.knowledge.api.dto;

import java.util.List;

/** 编辑抽屉回显的分片及其标准问法，不暴露内部同步字段。 */
public record KnowledgeChunkItem(
        Long id,
        Integer chunkNo,
        String content,
        List<String> questions) {
}
