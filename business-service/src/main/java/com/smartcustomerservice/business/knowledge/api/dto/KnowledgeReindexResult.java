package com.smartcustomerservice.business.knowledge.api.dto;

/**
 * 已发布知识重建索引的投递结果。
 *
 * @param queued 新建的Outbox事件数
 * @param reset  复用并重置的失败或待处理事件数
 * @param skipped 因版本状态、有效期或数据缺失而跳过的知识数
 */
public record KnowledgeReindexResult(int queued, int reset, int skipped) {
}
