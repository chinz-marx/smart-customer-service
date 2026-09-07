-- V16/V18已经在部分环境执行，不能删除历史迁移；本迁移向前撤销精确路由缓存模型。
DROP TABLE IF EXISTS learning.exact_tool_route;

ALTER TABLE learning.learning_problem
    DROP CONSTRAINT IF EXISTS ck_learning_problem_tool_resolution,
    DROP CONSTRAINT IF EXISTS ck_learning_problem_resolution_type,
    DROP COLUMN IF EXISTS route_published_at,
    DROP COLUMN IF EXISTS target_tool_name,
    DROP COLUMN IF EXISTS resolution_type;

-- Tool成功表达只服务于已撤销的精确路由审核，连同其派生样本一起清理。
DELETE FROM learning.learning_sample sample
USING learning.learning_signal signal
WHERE sample.signal_id = signal.id
  AND signal.source_type = 7;

DELETE FROM learning.learning_signal
WHERE source_type = 7;

ALTER TABLE learning.learning_signal
    DROP CONSTRAINT IF EXISTS ck_learning_signal_source;

ALTER TABLE learning.learning_signal
    ADD CONSTRAINT ck_learning_signal_source
        CHECK (source_type IN (1, 2, 3, 4, 5, 6));

COMMENT ON TABLE learning.learning_signal IS
    '没帮助、差评、申请人工、投诉、Tool失败和RAG无命中的原始信号';

COMMENT ON COLUMN learning.learning_signal.source_type IS
    '信号来源：1没帮助、2差评、3申请人工、4投诉、5 Tool失败、6 RAG无命中';
