package com.smartcustomerservice.business.knowledge.api.dto;

import com.smartcustomerservice.business.knowledge.domain.Knowledge;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeApproval;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeVersion;

import java.util.List;

/** 编辑抽屉需要同时知道线上版本、待审版本、审批单和分片问法。 */
public record KnowledgeDetail(
        Knowledge knowledge,
        String categoryName,
        KnowledgeVersion currentVersion,
        KnowledgeVersion pendingVersion,
        KnowledgeApproval latestApproval,
        List<KnowledgeChunkItem> chunks) {
}