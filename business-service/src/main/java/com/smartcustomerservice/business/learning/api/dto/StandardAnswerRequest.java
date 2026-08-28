package com.smartcustomerservice.business.learning.api.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/** 保存Python LLM生成后、审核员可继续编辑的标准回答草稿。 */
public record StandardAnswerRequest(
        @NotBlank @Size(max = 4000) String answer,
        @NotBlank @Size(max = 64) String provider,
        @NotBlank @Size(max = 128) String model) {
}
