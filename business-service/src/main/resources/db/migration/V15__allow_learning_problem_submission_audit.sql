ALTER TABLE learning.learning_problem_review
    DROP CONSTRAINT ck_learning_problem_review_action,
    ADD CONSTRAINT ck_learning_problem_review_action
        CHECK (action_type IN (1, 2, 3, 4, 5, 6, 7));

COMMENT ON COLUMN learning.learning_problem_review.action_type IS
    '动作：1生成回答、2编辑回答、3通过、4驳回、5忽略、6转知识、7提交审核';
