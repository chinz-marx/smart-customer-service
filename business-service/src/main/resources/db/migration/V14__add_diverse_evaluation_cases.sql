-- 把测试集多元性保存为结构化字段，并给困难负样本增加独立发布门槛指标。
ALTER TABLE learning.learning_evaluation_case
    ADD COLUMN case_category VARCHAR(32) NOT NULL DEFAULT 'conversational',
    ADD COLUMN difficulty SMALLINT NOT NULL DEFAULT 2,
    ADD COLUMN source_type SMALLINT NOT NULL DEFAULT 2,
    ADD COLUMN expected_match BOOLEAN NOT NULL DEFAULT TRUE,
    ADD CONSTRAINT ck_learning_case_category CHECK (
        case_category IN ('conversational', 'omitted', 'typo', 'inverted', 'boundary', 'hard_negative')
    ),
    ADD CONSTRAINT ck_learning_case_difficulty CHECK (difficulty IN (1, 2, 3)),
    ADD CONSTRAINT ck_learning_case_source_type CHECK (source_type IN (1, 2)),
    ADD CONSTRAINT ck_learning_case_negative_consistency CHECK (
        (case_category = 'hard_negative' AND expected_match = FALSE AND difficulty = 3)
        OR (case_category <> 'hard_negative' AND expected_match = TRUE)
    );

ALTER TABLE learning.learning_evaluation_run
    ADD COLUMN positive_cases INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN hard_negative_cases INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN hard_negative_false_positive_rate DOUBLE PRECISION,
    ADD CONSTRAINT ck_learning_evaluation_run_case_counts CHECK (
        positive_cases >= 0 AND hard_negative_cases >= 0
    );

ALTER TABLE learning.learning_evaluation_case_result
    ADD COLUMN expected_match BOOLEAN NOT NULL DEFAULT TRUE;

CREATE INDEX idx_learning_evaluation_case_diversity
    ON learning.learning_evaluation_case (version_id, expected_match, case_category);

COMMENT ON COLUMN learning.learning_evaluation_case.case_category IS
    'conversational口语、omitted省略、typo错别字、inverted倒装追问、boundary边界、hard_negative困难负样本';
COMMENT ON COLUMN learning.learning_evaluation_case.difficulty IS '1简单、2中等、3困难';
COMMENT ON COLUMN learning.learning_evaluation_case.source_type IS '1真实用户、2LLM生成';
COMMENT ON COLUMN learning.learning_evaluation_case.expected_match IS '是否应该召回当前候选知识';
COMMENT ON COLUMN learning.learning_evaluation_run.hard_negative_false_positive_rate IS
    '困难负样本在阈值内错误召回当前候选知识的比例';
