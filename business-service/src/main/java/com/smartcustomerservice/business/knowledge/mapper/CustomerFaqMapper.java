package com.smartcustomerservice.business.knowledge.mapper;

import com.smartcustomerservice.business.knowledge.api.dto.CustomerFaqAnswerSource;
import com.smartcustomerservice.business.knowledge.api.dto.CustomerFaqQuestion;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/** 客服常见问题只读取当前有效的已发布知识版本。 */
@Mapper
public interface CustomerFaqMapper {

    @Select("""
            WITH representative AS (
              SELECT DISTINCT ON (c.content_hash)
                     q.id AS question_id,
                     q.question_text,
                     v.published_at
              FROM business.kb_knowledge_question q
              JOIN business.kb_knowledge_chunk c ON c.id = q.chunk_id
              JOIN business.kb_knowledge k
                ON k.id = q.knowledge_id AND k.current_version_id = q.version_id
              JOIN business.kb_knowledge_version v ON v.id = q.version_id
              WHERE k.status = 1
                AND v.version_status = 2
                AND v.effective_at <= CURRENT_TIMESTAMP
                AND (v.expired_at IS NULL OR v.expired_at > CURRENT_TIMESTAMP)
              ORDER BY c.content_hash,
                       v.published_at DESC NULLS LAST,
                       q.question_no ASC,
                       q.id ASC
            )
            SELECT question_id, question_text
            FROM representative
            ORDER BY published_at DESC NULLS LAST, question_id ASC
            LIMIT #{limit} OFFSET #{offset}
            """)
    List<CustomerFaqQuestion> selectPublishedQuestions(
            @Param("limit") long limit,
            @Param("offset") long offset);

    @Select("""
            SELECT COUNT(DISTINCT c.content_hash)
            FROM business.kb_knowledge_question q
            JOIN business.kb_knowledge_chunk c ON c.id = q.chunk_id
            JOIN business.kb_knowledge k
              ON k.id = q.knowledge_id AND k.current_version_id = q.version_id
            JOIN business.kb_knowledge_version v ON v.id = q.version_id
            WHERE k.status = 1
              AND v.version_status = 2
              AND v.effective_at <= CURRENT_TIMESTAMP
              AND (v.expired_at IS NULL OR v.expired_at > CURRENT_TIMESTAMP)
            """)
    long countPublishedQuestions();

    @Select("""
            SELECT q.id AS question_id, q.question_text, c.chunk_content
            FROM business.kb_knowledge_question q
            JOIN business.kb_knowledge_chunk c ON c.id = q.chunk_id
            JOIN business.kb_knowledge k
              ON k.id = q.knowledge_id AND k.current_version_id = q.version_id
            JOIN business.kb_knowledge_version v ON v.id = q.version_id
            WHERE q.id = #{questionId}
              AND k.status = 1
              AND v.version_status = 2
              AND v.effective_at <= CURRENT_TIMESTAMP
              AND (v.expired_at IS NULL OR v.expired_at > CURRENT_TIMESTAMP)
            """)
    CustomerFaqAnswerSource selectPublishedAnswer(@Param("questionId") long questionId);
}
