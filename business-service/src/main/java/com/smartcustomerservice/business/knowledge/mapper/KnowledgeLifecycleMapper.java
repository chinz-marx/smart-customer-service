package com.smartcustomerservice.business.knowledge.mapper;

import com.smartcustomerservice.business.knowledge.sync.ExpiredKnowledgeItem;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/** 使用数据库时间筛选已失效知识，避免应用服务器时区造成边界偏差。 */
@Mapper
public interface KnowledgeLifecycleMapper {
    @Select("""
            SELECT k.id AS knowledge_id, k.knowledge_code, v.id AS version_id
            FROM business.kb_knowledge k
            JOIN business.kb_knowledge_version v ON v.id = k.current_version_id
            WHERE k.status = 1
              AND k.pending_version_id IS NULL
              AND v.expired_at IS NOT NULL
              AND v.expired_at <= CURRENT_TIMESTAMP
            ORDER BY v.expired_at ASC
            LIMIT 100
            """)
    List<ExpiredKnowledgeItem> selectExpiredKnowledge();
}
