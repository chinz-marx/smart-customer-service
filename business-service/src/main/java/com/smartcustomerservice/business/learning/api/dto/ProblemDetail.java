package com.smartcustomerservice.business.learning.api.dto;

import java.util.List;

/** 问题详情包含聚类统计、最多十条样本和完整审核历史。 */
public record ProblemDetail(
        ProblemListItem problem,
        List<ProblemSampleItem> samples,
        List<ProblemReviewItem> reviews) {
}
