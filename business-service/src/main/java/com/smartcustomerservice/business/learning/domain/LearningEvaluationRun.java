package com.smartcustomerservice.business.learning.domain;

import com.baomidou.mybatisplus.annotation.FieldStrategy;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.smartcustomerservice.business.knowledge.persistence.JsonbStringTypeHandler;
import lombok.Data;
import org.apache.ibatis.type.JdbcType;

import java.time.OffsetDateTime;

/** 一次知识候选版本的自动发布验收批次。 */
@Data
@TableName(value = "learning_evaluation_run", schema = "learning", autoResultMap = true)
public class LearningEvaluationRun {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String runNo;
    private Long problemId;
    private Long knowledgeId;
    private Long versionId;
    private Long approvalId;
    private Integer status;
    private Integer retryCount;
    private OffsetDateTime nextRetryAt;
    private Integer totalCases;
    // MyBatis 的驼峰转换不会在数字前自动补下划线，因此这两个字段显式绑定数据库列名。
    @TableField("recall_at_1")
    private Double recallAt1;
    @TableField("recall_at_3")
    private Double recallAt3;
    private Double thresholdRecall;
    private Integer positiveCases;
    private Integer hardNegativeCases;
    private Double hardNegativeFalsePositiveRate;
    private Integer errorCount;
    private Double averageLatencyMs;
    private Double p95LatencyMs;
    private Double distanceThreshold;
    @TableField(typeHandler = JsonbStringTypeHandler.class, jdbcType = JdbcType.OTHER)
    private String metrics;
    @TableField(updateStrategy = FieldStrategy.ALWAYS)
    private String errorMessage;
    private OffsetDateTime startedAt;
    private OffsetDateTime finishedAt;
    private OffsetDateTime createdAt;
    @TableField(updateStrategy = FieldStrategy.ALWAYS)
    private OffsetDateTime processedAt;
}
