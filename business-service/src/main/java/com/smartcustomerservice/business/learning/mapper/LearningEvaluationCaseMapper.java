package com.smartcustomerservice.business.learning.mapper;

import com.smartcustomerservice.business.learning.api.dto.EvaluationCaseListItem;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.OffsetDateTime;
import java.util.List;

/** 测试用例与知识版本绑定，审批状态变化时按version_id批量更新。 */
@Mapper
public interface LearningEvaluationCaseMapper {
    @Insert("""
            INSERT INTO learning.learning_evaluation_case (
                case_code, problem_id, knowledge_id, version_id, case_no,
                question_text, expected_answer, expected_intent, case_type,
                status, generated_provider, generated_model, created_by,
                case_category, difficulty, source_type, expected_match
            ) VALUES (
                #{caseCode}, #{problemId}, #{knowledgeId}, #{versionId}, #{caseNo},
                #{question}, #{expectedAnswer}, #{expectedIntent}, 1,
                0, #{provider}, #{model}, #{operatorId},
                #{caseCategory}, #{difficulty}, #{sourceType}, #{expectedMatch}
            )
            """)
    int insertCase(
            @Param("caseCode") String caseCode,
            @Param("problemId") long problemId,
            @Param("knowledgeId") long knowledgeId,
            @Param("versionId") long versionId,
            @Param("caseNo") int caseNo,
            @Param("question") String question,
            @Param("expectedAnswer") String expectedAnswer,
            @Param("expectedIntent") String expectedIntent,
            @Param("provider") String provider,
            @Param("model") String model,
            @Param("operatorId") String operatorId,
            @Param("caseCategory") String caseCategory,
            @Param("difficulty") int difficulty,
            @Param("sourceType") int sourceType,
            @Param("expectedMatch") boolean expectedMatch);

    @Select("""
            SELECT COUNT(*)
            FROM learning.learning_evaluation_case
            WHERE version_id = #{versionId} AND status = 0
            """)
    int countPendingByVersion(@Param("versionId") long versionId);

    @Select("""
            SELECT problem_id
            FROM learning.learning_evaluation_case
            WHERE version_id = #{versionId}
            ORDER BY id
            LIMIT 1
            """)
    Long selectProblemIdByVersion(@Param("versionId") long versionId);

    @Select("""
            SELECT id, question_text, expected_intent, expected_match
            FROM learning.learning_evaluation_case
            WHERE version_id = #{versionId} AND status = 1
            ORDER BY case_no, id
            """)
    List<EvaluationCaseExecutionItem> selectForEvaluation(
            @Param("versionId") long versionId);

    /** 人工审核通过后，用例先等待自动发布验收，不能提前进入正式回归集。 */
    @Update("""
            UPDATE learning.learning_evaluation_case
            SET status = 1, processed_at = NULL
            WHERE version_id = #{versionId} AND status = 0
            """)
    int markPendingEvaluation(@Param("versionId") long versionId);

    /** 自动验收通过后，测试用例才成为正式、已生效的回归用例。 */
    @Update("""
            UPDATE learning.learning_evaluation_case
            SET status = 3, approved_by = #{operatorId}, approved_at = #{now}, processed_at = #{now}
            WHERE version_id = #{versionId} AND status = 1
            """)
    int activateByVersion(
            @Param("versionId") long versionId,
            @Param("operatorId") String operatorId,
            @Param("now") OffsetDateTime now);

    @Update("""
            UPDATE learning.learning_evaluation_case
            SET status = 2, approved_by = #{operatorId}, approved_at = #{now}, processed_at = #{now}
            WHERE version_id = #{versionId} AND status IN (0, 1)
            """)
    int rejectByVersion(
            @Param("versionId") long versionId,
            @Param("operatorId") String operatorId,
            @Param("now") OffsetDateTime now);

    @Select("""
            <script>
            SELECT c.id, c.case_code, p.problem_code, k.knowledge_code,
                   v.title AS knowledge_title, c.version_id, v.version_no,
                   c.question_text, c.expected_answer,
                   c.expected_intent, c.case_type, c.case_category, c.difficulty,
                   c.source_type, c.expected_match, c.status, c.generated_model,
                   c.created_by, c.approved_by, c.created_at, c.approved_at
            FROM learning.learning_evaluation_case c
            JOIN learning.learning_problem p ON p.id = c.problem_id
            JOIN business.kb_knowledge k ON k.id = c.knowledge_id
            JOIN business.kb_knowledge_version v ON v.id = c.version_id
            WHERE 1 = 1
            <if test="status != null">AND c.status = #{status}</if>
            <if test="keyword != null and keyword != ''">
              AND (c.question_text ILIKE CONCAT('%', #{keyword}, '%')
                   OR v.title ILIKE CONCAT('%', #{keyword}, '%')
                   OR p.problem_code ILIKE CONCAT('%', #{keyword}, '%'))
            </if>
            ORDER BY c.created_at DESC, c.id DESC
            LIMIT #{limit} OFFSET #{offset}
            </script>
            """)
    List<EvaluationCaseListItem> selectPage(
            @Param("keyword") String keyword,
            @Param("status") Integer status,
            @Param("limit") long limit,
            @Param("offset") long offset);

    @Select("""
            <script>
            SELECT COUNT(*)
            FROM learning.learning_evaluation_case c
            JOIN learning.learning_problem p ON p.id = c.problem_id
            JOIN business.kb_knowledge_version v ON v.id = c.version_id
            WHERE 1 = 1
            <if test="status != null">AND c.status = #{status}</if>
            <if test="keyword != null and keyword != ''">
              AND (c.question_text ILIKE CONCAT('%', #{keyword}, '%')
                   OR v.title ILIKE CONCAT('%', #{keyword}, '%')
                   OR p.problem_code ILIKE CONCAT('%', #{keyword}, '%'))
            </if>
            </script>
            """)
    long countPage(@Param("keyword") String keyword, @Param("status") Integer status);

    /** 发送给 Python 正式评测执行器的最小用例结构。 */
    record EvaluationCaseExecutionItem(
            long id, String questionText, String expectedIntent, boolean expectedMatch) {
    }
}
