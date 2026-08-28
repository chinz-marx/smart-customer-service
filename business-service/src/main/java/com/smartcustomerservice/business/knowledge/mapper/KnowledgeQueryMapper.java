package com.smartcustomerservice.business.knowledge.mapper;

import com.smartcustomerservice.business.knowledge.api.dto.ApprovalListItem;
import com.smartcustomerservice.business.knowledge.api.dto.KnowledgeListItem;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/** 只读列表使用明确 SQL，避免在 Java 内存中对两万条知识做筛选和分页。 */
@Mapper
public interface KnowledgeQueryMapper {
    @Select("SELECT COALESCE(MAX(version_no), 0) + 1 "
            + "FROM business.kb_knowledge_version WHERE knowledge_id = #{knowledgeId}")
    int selectNextVersionNo(@Param("knowledgeId") long knowledgeId);

    @Select("""
            <script>
            SELECT k.id, k.knowledge_code, k.category_id, c.category_name, k.status,
                   v.id AS version_id, v.version_no, v.version_status, v.title, v.intent_code,
                   k.created_by, k.updated_by, a.approver_id, a.rejection_reason,
                   k.created_at, v.published_at
            FROM business.kb_knowledge k
            JOIN business.kb_category c ON c.id = k.category_id
            JOIN business.kb_knowledge_version v
              ON v.id =
              <choose>
                <when test="view == 'published'">k.current_version_id</when>
                <when test="view == 'pending'">k.pending_version_id</when>
                <otherwise>COALESCE(k.pending_version_id, k.current_version_id)</otherwise>
              </choose>
            LEFT JOIN LATERAL (
                SELECT approval.approver_id, approval.rejection_reason
                FROM business.kb_approval approval
                WHERE approval.knowledge_id = k.id
                ORDER BY approval.id DESC LIMIT 1
            ) a ON TRUE
            WHERE 1 = 1
            <if test="keyword != null and keyword != ''">
              AND (v.title ILIKE CONCAT('%', #{keyword}, '%')
                   OR v.content ILIKE CONCAT('%', #{keyword}, '%'))
            </if>
            <if test="categoryId != null">AND k.category_id = #{categoryId}</if>
            <if test="view == 'pending'">AND k.pending_version_id IS NOT NULL</if>
            <if test="view == 'published'">AND k.status = 1 AND k.current_version_id IS NOT NULL</if>
            <if test="view == 'disabled'">
              AND k.status = 0 AND k.current_version_id IS NOT NULL AND k.pending_version_id IS NULL
            </if>
            ORDER BY k.updated_at DESC, k.id DESC
            LIMIT #{limit} OFFSET #{offset}
            </script>
            """)
    List<KnowledgeListItem> selectPage(
            @Param("keyword") String keyword,
            @Param("categoryId") Long categoryId,
            @Param("view") String view,
            @Param("limit") long limit,
            @Param("offset") long offset);

    @Select("""
            <script>
            SELECT COUNT(*)
            FROM business.kb_knowledge k
            JOIN business.kb_knowledge_version v
              ON v.id =
              <choose>
                <when test="view == 'published'">k.current_version_id</when>
                <when test="view == 'pending'">k.pending_version_id</when>
                <otherwise>COALESCE(k.pending_version_id, k.current_version_id)</otherwise>
              </choose>
            WHERE 1 = 1
            <if test="keyword != null and keyword != ''">
              AND (v.title ILIKE CONCAT('%', #{keyword}, '%')
                   OR v.content ILIKE CONCAT('%', #{keyword}, '%'))
            </if>
            <if test="categoryId != null">AND k.category_id = #{categoryId}</if>
            <if test="view == 'pending'">AND k.pending_version_id IS NOT NULL</if>
            <if test="view == 'published'">AND k.status = 1 AND k.current_version_id IS NOT NULL</if>
            <if test="view == 'disabled'">
              AND k.status = 0 AND k.current_version_id IS NOT NULL AND k.pending_version_id IS NULL
            </if>
            </script>
            """)
    long countPage(
            @Param("keyword") String keyword,
            @Param("categoryId") Long categoryId,
            @Param("view") String view);

    @Select("""
            SELECT a.id AS approval_id, a.approval_no, a.knowledge_id, a.version_id,
                   a.action_type, v.title, c.category_name, v.version_no,
                   a.applicant_id, a.application_reason, a.submitted_at
            FROM business.kb_approval a
            JOIN business.kb_knowledge k ON k.id = a.knowledge_id
            JOIN business.kb_knowledge_version v ON v.id = a.version_id
            JOIN business.kb_category c ON c.id = k.category_id
            WHERE a.status = 0
            ORDER BY a.submitted_at ASC, a.id ASC
            LIMIT #{limit} OFFSET #{offset}
            """)
    List<ApprovalListItem> selectPendingApprovals(
            @Param("limit") long limit, @Param("offset") long offset);

    @Select("SELECT COUNT(*) FROM business.kb_approval WHERE status = 0")
    long countPendingApprovals();
}
