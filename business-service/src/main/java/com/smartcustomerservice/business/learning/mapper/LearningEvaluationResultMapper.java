package com.smartcustomerservice.business.learning.mapper;

import com.smartcustomerservice.business.learning.api.dto.EvaluationRunCaseResultItem;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/** 保存每条用例在真实 Redis Search 竞争召回中的结果。 */
@Mapper
public interface LearningEvaluationResultMapper {
    @Select("""
            SELECT c.id AS case_id, c.case_code, c.question_text, c.case_category,
                   c.difficulty, r.expected_match, r.passed_at_1, r.passed_at_3,
                   r.passed_threshold, r.top_distance, r.latency_ms, r.error_message
            FROM learning.learning_evaluation_case_result r
            JOIN learning.learning_evaluation_case c ON c.id = r.case_id
            WHERE r.run_id = #{runId}
            ORDER BY c.case_no, c.id
            """)
    List<EvaluationRunCaseResultItem> selectByRunId(@Param("runId") long runId);

    @Insert("""
            INSERT INTO learning.learning_evaluation_case_result (
                run_id, case_id, passed_at_1, passed_at_3, passed_threshold,
                top_knowledge_id, top_version_id, top_chunk_no, top_distance,
                latency_ms, error_message, expected_match
            ) VALUES (
                #{runId}, #{caseId}, #{passedAt1}, #{passedAt3}, #{passedThreshold},
                #{topKnowledgeId}, #{topVersionId}, #{topChunkNo}, #{topDistance},
                #{latencyMs}, #{errorMessage}, #{expectedMatch}
            )
            ON CONFLICT (run_id, case_id) DO UPDATE SET
                passed_at_1 = EXCLUDED.passed_at_1,
                passed_at_3 = EXCLUDED.passed_at_3,
                passed_threshold = EXCLUDED.passed_threshold,
                top_knowledge_id = EXCLUDED.top_knowledge_id,
                top_version_id = EXCLUDED.top_version_id,
                top_chunk_no = EXCLUDED.top_chunk_no,
                top_distance = EXCLUDED.top_distance,
                latency_ms = EXCLUDED.latency_ms,
                error_message = EXCLUDED.error_message,
                expected_match = EXCLUDED.expected_match,
                processed_at = CURRENT_TIMESTAMP
            """)
    int upsert(
            @Param("runId") long runId,
            @Param("caseId") long caseId,
            @Param("expectedMatch") boolean expectedMatch,
            @Param("passedAt1") boolean passedAt1,
            @Param("passedAt3") boolean passedAt3,
            @Param("passedThreshold") boolean passedThreshold,
            @Param("topKnowledgeId") Long topKnowledgeId,
            @Param("topVersionId") Long topVersionId,
            @Param("topChunkNo") Integer topChunkNo,
            @Param("topDistance") Double topDistance,
            @Param("latencyMs") double latencyMs,
            @Param("errorMessage") String errorMessage);
}
