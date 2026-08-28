package com.smartcustomerservice.business.learning.mapper;

import com.smartcustomerservice.business.learning.api.dto.ProblemListItem;
import com.smartcustomerservice.business.learning.api.dto.ProblemReviewItem;
import com.smartcustomerservice.business.learning.api.dto.ProblemSampleItem;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/** 问题列表使用数据库分页和聚合，避免把大量样本加载到Java内存。 */
@Mapper
public interface LearningProblemQueryMapper {
    String PROBLEM_COLUMNS = """
            p.id, p.problem_code, p.representative_question, p.problem_summary,
            p.intent_code, stats.confidence, main_source.source_type,
            p.occurrence_count, p.affected_user_count, p.conversation_count,
            p.priority, p.status, p.standard_answer, p.answer_provider,
            p.answer_model, p.answer_generated_by, p.answer_generated_at,
            p.reviewed_by, p.reviewed_at, p.review_comment, p.rejection_reason,
            p.review_version, p.converted_knowledge_id, p.converted_version_id,
            p.converted_approval_id, p.converted_by, p.converted_at,
            p.first_seen_at, p.last_seen_at
            """;

    String PROBLEM_JOINS = """
            LEFT JOIN LATERAL (
                SELECT AVG(signal.confidence)::DOUBLE PRECISION AS confidence
                FROM learning.learning_sample sample
                JOIN learning.learning_signal signal ON signal.id = sample.signal_id
                WHERE sample.problem_id = p.id AND signal.confidence IS NOT NULL
            ) stats ON TRUE
            LEFT JOIN LATERAL (
                SELECT signal.source_type
                FROM learning.learning_sample sample
                JOIN learning.learning_signal signal ON signal.id = sample.signal_id
                WHERE sample.problem_id = p.id
                GROUP BY signal.source_type
                ORDER BY COUNT(*) DESC, signal.source_type ASC
                LIMIT 1
            ) main_source ON TRUE
            """;

    @Select("""
            <script>
            """ + "SELECT " + PROBLEM_COLUMNS + " FROM learning.learning_problem p " + PROBLEM_JOINS + """
            WHERE 1 = 1
            <if test="keyword != null and keyword != ''">
              AND (p.problem_summary ILIKE CONCAT('%', #{keyword}, '%')
                   OR p.representative_question ILIKE CONCAT('%', #{keyword}, '%')
                   OR p.problem_code ILIKE CONCAT('%', #{keyword}, '%'))
            </if>
            <if test="status != null">AND p.status = #{status}</if>
            <if test="sourceType != null">
              AND EXISTS (
                  SELECT 1 FROM learning.learning_sample source_sample
                  JOIN learning.learning_signal source_signal ON source_signal.id = source_sample.signal_id
                  WHERE source_sample.problem_id = p.id AND source_signal.source_type = #{sourceType}
              )
            </if>
            ORDER BY p.priority DESC, p.last_seen_at DESC, p.id DESC
            LIMIT #{limit} OFFSET #{offset}
            </script>
            """)
    List<ProblemListItem> selectPage(
            @Param("keyword") String keyword,
            @Param("status") Integer status,
            @Param("sourceType") Integer sourceType,
            @Param("limit") long limit,
            @Param("offset") long offset);

    @Select("""
            <script>
            SELECT COUNT(*) FROM learning.learning_problem p
            WHERE 1 = 1
            <if test="keyword != null and keyword != ''">
              AND (p.problem_summary ILIKE CONCAT('%', #{keyword}, '%')
                   OR p.representative_question ILIKE CONCAT('%', #{keyword}, '%')
                   OR p.problem_code ILIKE CONCAT('%', #{keyword}, '%'))
            </if>
            <if test="status != null">AND p.status = #{status}</if>
            <if test="sourceType != null">
              AND EXISTS (
                  SELECT 1 FROM learning.learning_sample source_sample
                  JOIN learning.learning_signal source_signal ON source_signal.id = source_sample.signal_id
                  WHERE source_sample.problem_id = p.id AND source_signal.source_type = #{sourceType}
              )
            </if>
            </script>
            """)
    long countPage(
            @Param("keyword") String keyword,
            @Param("status") Integer status,
            @Param("sourceType") Integer sourceType);

    @Select("SELECT " + PROBLEM_COLUMNS + " FROM learning.learning_problem p "
            + PROBLEM_JOINS + " WHERE p.id = #{id}")
    ProblemListItem selectProblem(@Param("id") long id);

    @Select("""
            SELECT sample.id, sample.root_question, sample.original_answer,
                   signal.source_type, signal.confidence, signal.conversation_id,
                   signal.occurred_at
            FROM learning.learning_sample sample
            JOIN learning.learning_signal signal ON signal.id = sample.signal_id
            WHERE sample.problem_id = #{problemId}
            ORDER BY signal.occurred_at DESC, sample.id DESC
            LIMIT 10
            """)
    List<ProblemSampleItem> selectSamples(@Param("problemId") long problemId);

    @Select("""
            SELECT id, action_type, status_before, status_after, answer_snapshot,
                   comment, operator_id, created_at, processed_at
            FROM learning.learning_problem_review
            WHERE problem_id = #{problemId}
            ORDER BY created_at DESC, id DESC
            """)
    List<ProblemReviewItem> selectReviews(@Param("problemId") long problemId);
}
