package com.smartcustomerservice.business.learning.api.dto;

import jakarta.validation.constraints.Future;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

import java.time.OffsetDateTime;
import java.util.List;

/** 已审核问题转换为知识审批单和回归测试集的请求。 */
public record LearningConversionRequest(
        @NotNull Long categoryId,
        @NotBlank @Size(max = 256) String title,
        @Size(max = 20) List<@Size(max = 64) String> tags,
        @NotNull OffsetDateTime effectiveAt,
        @Future OffsetDateTime expiredAt,
        @NotEmpty @Size(max = 8) List<@NotBlank String> standardQuestions,
        @NotEmpty @Size(min = 8, max = 15) List<@NotNull TestCaseDraft> testCases,
        @NotBlank @Size(max = 64) String provider,
        @NotBlank @Size(max = 128) String model) {

    /** 页面可编辑但必须保留多元类别和困难负样本语义。 */
    public record TestCaseDraft(
            @NotBlank String question,
            @NotBlank @Size(max = 32) String caseCategory,
            @NotNull Integer difficulty,
            @NotNull Integer sourceType,
            @NotNull Boolean expectedMatch) {
    }
}
