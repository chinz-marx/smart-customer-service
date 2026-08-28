package com.smartcustomerservice.business.knowledge.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeOutboxEvent;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

public interface KnowledgeOutboxEventMapper extends BaseMapper<KnowledgeOutboxEvent> {
    /** 查询同一线上版本尚未完成的最新发布事件，供全量重建时复用。 */
    @Select("""
            SELECT *
            FROM business.kb_outbox_event
            WHERE knowledge_id = #{knowledgeId}
              AND version_id = #{versionId}
              AND event_type = 1
              AND status IN (0, 1, 3)
            ORDER BY id DESC
            LIMIT 1
            """)
    KnowledgeOutboxEvent selectLatestUnfinishedUpsert(
            @Param("knowledgeId") Long knowledgeId,
            @Param("versionId") Long versionId);
}
