-- 成功执行过的Tool用户表达进入现有问题学习链路，经聚类和人工审核后才可发布精确路由。
ALTER TABLE learning.learning_signal
    DROP CONSTRAINT ck_learning_signal_source;

ALTER TABLE learning.learning_signal
    ADD CONSTRAINT ck_learning_signal_source
        CHECK (source_type IN (1, 2, 3, 4, 5, 6, 7));

COMMENT ON TABLE learning.learning_signal IS
    '没帮助、差评、申请人工、投诉、Tool失败、RAG无命中和Tool成功表达的原始信号';

COMMENT ON COLUMN learning.learning_signal.source_type IS
    '信号来源：1没帮助、2差评、3申请人工、4投诉、5 Tool失败、6 RAG无命中、7 Tool成功表达';
