package com.smartcustomerservice.business.learning.mapper;

import com.smartcustomerservice.business.learning.api.dto.ProblemListItem;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.OffsetDateTime;

/** 所有审核写操作集中在一个Mapper，Service在事务中先加行锁再修改。 */
@Mapper
public interface LearningProblemCommandMapper {
    @Select("""
            SELECT id, problem_code, representative_question, problem_summary,
                   intent_code, NULL::DOUBLE PRECISION AS confidence,
                   NULL::INTEGER AS source_type, occurrence_count, affected_user_count,
                   conversation_count, priority, status, standard_answer,
                   answer_provider, answer_model, answer_generated_by,
                   answer_generated_at, reviewed_by, reviewed_at, review_comment,
                   rejection_reason, review_version, converted_knowledge_id,
                   converted_version_id, converted_approval_id, converted_by,
                   converted_at, first_seen_at, last_seen_at
            FROM learning.learning_problem WHERE id = #{id} FOR UPDATE
            """)
    ProblemListItem selectForUpdate(@Param("id") long id);

    @Update("""
            UPDATE learning.learning_problem
            SET standard_answer = #{answer}, answer_provider = #{provider},
                answer_model = #{model}, answer_generated_by = #{operatorId},
                answer_generated_at = #{generatedAt}, review_version = review_version + 1,
                updated_by = #{operatorId}
            WHERE id = #{id}
            """)
    int updateAnswer(
            @Param("id") long id,
            @Param("answer") String answer,
            @Param("provider") String provider,
            @Param("model") String model,
            @Param("operatorId") String operatorId,
            @Param("generatedAt") OffsetDateTime generatedAt);

    @Update("""
            UPDATE learning.learning_problem
            SET status = 1, review_version = review_version + 1,
                updated_by = #{operatorId}
            WHERE id = #{id} AND status = 0
            """)
    int submitForReview(
            @Param("id") long id,
            @Param("operatorId") String operatorId);

    @Update("""
            UPDATE learning.learning_problem
            SET status = #{status}, reviewed_by = #{operatorId}, reviewed_at = #{reviewedAt},
                review_comment = #{comment}, rejection_reason = #{rejectionReason},
                review_version = review_version + 1, updated_by = #{operatorId}
            WHERE id = #{id}
            """)
    int updateDecision(
            @Param("id") long id,
            @Param("status") int status,
            @Param("operatorId") String operatorId,
            @Param("reviewedAt") OffsetDateTime reviewedAt,
            @Param("comment") String comment,
            @Param("rejectionReason") String rejectionReason);

    @Insert("""
            INSERT INTO learning.learning_problem_review (
                problem_id, action_type, status_before, status_after,
                answer_snapshot, comment, operator_id
            ) VALUES (
                #{problemId}, #{actionType}, #{statusBefore}, #{statusAfter},
                #{answerSnapshot}, #{comment}, #{operatorId}
            )
            """)
    int insertReview(
            @Param("problemId") long problemId,
            @Param("actionType") int actionType,
            @Param("statusBefore") int statusBefore,
            @Param("statusAfter") int statusAfter,
            @Param("answerSnapshot") String answerSnapshot,
            @Param("comment") String comment,
            @Param("operatorId") String operatorId);

    @Update("""
            UPDATE learning.learning_problem
            SET status = 4, converted_knowledge_id = #{knowledgeId},
                converted_version_id = #{versionId}, converted_approval_id = #{approvalId},
                converted_by = #{operatorId}, converted_at = #{now},
                review_version = review_version + 1, updated_by = #{operatorId}
            WHERE id = #{problemId} AND status = 2
            """)
    int markConverted(
            @Param("problemId") long problemId,
            @Param("knowledgeId") long knowledgeId,
            @Param("versionId") long versionId,
            @Param("approvalId") long approvalId,
            @Param("operatorId") String operatorId,
            @Param("now") OffsetDateTime now);

    @Update("""
            UPDATE learning.learning_problem
            SET status = 2, converted_knowledge_id = NULL, converted_version_id = NULL,
                converted_approval_id = NULL, converted_by = NULL, converted_at = NULL,
                review_version = review_version + 1,
                updated_by = #{operatorId}
            WHERE converted_version_id = #{versionId} AND status = 4
            """)
    int restoreApprovedByVersion(
            @Param("versionId") long versionId,
            @Param("operatorId") String operatorId);
}
