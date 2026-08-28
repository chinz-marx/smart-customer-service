package com.smartcustomerservice.business.learning.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.smartcustomerservice.business.learning.api.dto.EvaluationRunListItem;
import com.smartcustomerservice.business.learning.domain.LearningEvaluationRun;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.time.OffsetDateTime;
import java.util.List;

/** 自动发布验收批次的写入和后台列表查询。 */
@Mapper
public interface LearningEvaluationRunMapper extends BaseMapper<LearningEvaluationRun> {
    @Select("""
            SELECT *
            FROM learning.learning_evaluation_run
            WHERE (status = 0 AND next_retry_at <= #{now})
               OR (status = 1 AND processed_at < #{staleAt})
            ORDER BY id
            LIMIT #{limit}
            """)
    List<LearningEvaluationRun> selectReady(
            @Param("now") OffsetDateTime now,
            @Param("staleAt") OffsetDateTime staleAt,
            @Param("limit") int limit);

    @Select("""
            SELECT r.id, r.run_no, p.problem_code, k.knowledge_code, v.title AS knowledge_title,
                   r.version_id, v.version_no,
                   r.status, r.retry_count, r.total_cases, r.recall_at_1, r.recall_at_3,
                   r.threshold_recall, r.positive_cases, r.hard_negative_cases,
                   r.hard_negative_false_positive_rate, r.error_count,
                   r.average_latency_ms, r.p95_latency_ms,
                   r.distance_threshold, r.error_message, r.started_at, r.finished_at, r.created_at
            FROM learning.learning_evaluation_run r
            JOIN learning.learning_problem p ON p.id = r.problem_id
            JOIN business.kb_knowledge k ON k.id = r.knowledge_id
            JOIN business.kb_knowledge_version v ON v.id = r.version_id
            ORDER BY r.created_at DESC, r.id DESC
            LIMIT #{limit} OFFSET #{offset}
            """)
    List<EvaluationRunListItem> selectPage(
            @Param("limit") long limit, @Param("offset") long offset);

    @Select("SELECT COUNT(*) FROM learning.learning_evaluation_run")
    long countAll();
}
