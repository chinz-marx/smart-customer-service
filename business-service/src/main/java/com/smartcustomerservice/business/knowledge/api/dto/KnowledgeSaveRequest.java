package com.smartcustomerservice.business.knowledge.api.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import lombok.Data;

import java.time.OffsetDateTime;
import java.util.List;

/** 新增和修改知识使用同一组可编辑字段。 */
@Data
public class KnowledgeSaveRequest {
    @NotBlank(message = "标题不能为空")
    @Size(max = 256, message = "标题不能超过256个字符")
    private String title;

    @NotNull(message = "必须选择知识分类")
    private Long categoryId;

    @NotBlank(message = "知识内容不能为空")
    private String content;

    @Size(max = 20, message = "标签最多20个")
    private List<@Size(max = 64, message = "单个标签不能超过64个字符") String> tags;

    @NotBlank(message = "意图编码不能为空")
    @Size(max = 64, message = "意图编码不能超过64个字符")
    private String intentCode;

    @NotNull(message = "生效时间不能为空")
    private OffsetDateTime effectiveAt;
    private OffsetDateTime expiredAt;

    @Size(max = 1000, message = "申请说明不能超过1000个字符")
    private String applicationReason;

    @NotNull(message = "必须生成原子分片")
    @Valid
    @Size(min = 1, max = 100, message = "原子分片数量必须在1到100之间")
    private List<ChunkDraft> chunks;

    /** 页面审核确认后的原子分片；列表顺序即稳定的chunk_no。 */
    @Data
    public static class ChunkDraft {
        @NotBlank(message = "原子分片内容不能为空")
        private String content;

        @Size(min = 1, max = 8, message = "每个分片必须包含1到8个标准问法")
        private List<@NotBlank(message = "标准问法不能为空") String> questions;
    }
}