package com.smartcustomerservice.business.knowledge.api.dto;

/** Redis缺失时从当前已发布知识版本读取的确定性问答。 */
public record CustomerFaqAnswerSource(
        Long questionId,
        String questionText,
        String chunkContent) {
}
