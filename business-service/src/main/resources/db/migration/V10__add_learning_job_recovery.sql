-- Python定时任务异常退出时，processing_started_at用于识别并重新领取长时间卡住的信号。
ALTER TABLE learning.learning_signal
    ADD COLUMN processing_started_at TIMESTAMPTZ;

CREATE INDEX idx_learning_signal_processing_started
    ON learning.learning_signal (processing_started_at, id)
    WHERE process_status = 1;

COMMENT ON COLUMN learning.learning_signal.processing_started_at
    IS '后台任务开始处理时间；超过恢复期限仍为处理中时可重新入队';
