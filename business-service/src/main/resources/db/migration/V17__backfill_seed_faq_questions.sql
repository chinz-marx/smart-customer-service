-- V3 的初始 FAQ 在 V4 标准问法表创建之前已经发布，因此没有 question 记录。
-- 使用每条 FAQ 的已发布标题作为第一条标准问法，使客服页面和 Redis question-map 完整。
INSERT INTO business.kb_knowledge_question (
    knowledge_id, version_id, chunk_id, question_no,
    question_text, question_hash, sync_status
)
SELECT
    k.id,
    v.id,
    c.id,
    0,
    btrim(v.title),
    encode(sha256(convert_to(btrim(v.title), 'UTF8')), 'hex'),
    0
FROM business.kb_knowledge k
JOIN business.kb_category category
  ON category.id = k.category_id AND category.category_code = 'faq'
JOIN business.kb_knowledge_version v
  ON v.id = k.current_version_id
JOIN LATERAL (
    SELECT chunk.id
    FROM business.kb_knowledge_chunk chunk
    WHERE chunk.version_id = v.id
    ORDER BY chunk.chunk_no ASC, chunk.id ASC
    LIMIT 1
) c ON TRUE
WHERE k.status = 1
  AND v.version_status = 2
  AND NOT EXISTS (
      SELECT 1
      FROM business.kb_knowledge_question existing
      WHERE existing.version_id = v.id
  )
ON CONFLICT (chunk_id, question_no) DO NOTHING;

COMMENT ON TABLE business.kb_knowledge_question IS
    '原子分片的标准问法；FAQ分类问法同时用于客服常见问题精确映射';
